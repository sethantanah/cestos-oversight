"""Request-wide Supervisor visibility for ORM employee reads and related records."""

from datetime import date

from sqlalchemy import Text, and_, event, false, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.dependencies import scoped_roles
from app.models import AuditLog, Employee, EmployeeAssignment
from app.db.base import Base


def is_scoped_supervisor(actor):
    # Other domain-role grants do not silently widen a Supervisor's employee scope.
    return bool(actor and not actor.is_superuser and any(
        role.name.strip().casefold() == "supervisor" for role in scoped_roles(actor)
    ))


def supervised_employee_ids(actor, *, include_self=False):
    # Core aliases deliberately avoid recursively applying ORM visibility to the
    # supervisor lookup or the assignment that establishes the access grant.
    employees = Employee.__table__.alias("supervised_people")
    supervisors = Employee.__table__.alias("supervisor_profiles")
    assignments = EmployeeAssignment.__table__.alias("supervised_assignments")
    own_ids = select(supervisors.c.id).where(
        supervisors.c.organization_id == actor.organization_id,
        supervisors.c.user_id == actor.id,
        supervisors.c.is_active.is_(True),
        supervisors.c.archived_at.is_(None),
    )
    active_assignments = select(assignments.c.employee_id).where(
        assignments.c.organization_id == actor.organization_id,
        assignments.c.supervisor_id.in_(own_ids),
        assignments.c.status == "ACTIVE",
        assignments.c.start_date <= date.today(),
        or_(assignments.c.end_date.is_(None), assignments.c.end_date >= date.today()),
    )
    team_project_ids = select(assignments.c.project_id).where(
        assignments.c.organization_id == actor.organization_id,
        assignments.c.status == "ACTIVE",
        assignments.c.start_date <= date.today(),
        or_(assignments.c.end_date.is_(None), assignments.c.end_date >= date.today()),
        or_(assignments.c.supervisor_id.in_(own_ids), assignments.c.employee_id.in_(own_ids)),
    )
    coworkers = select(assignments.c.employee_id).where(
        assignments.c.organization_id == actor.organization_id,
        assignments.c.project_id.in_(team_project_ids),
        assignments.c.status == "ACTIVE",
        assignments.c.start_date <= date.today(),
        or_(assignments.c.end_date.is_(None), assignments.c.end_date >= date.today()),
    )
    grants = [employees.c.supervisor_id.in_(own_ids), employees.c.id.in_(active_assignments),
              employees.c.id.in_(coworkers)]
    if include_self:
        grants.append(employees.c.user_id == actor.id)
    return select(employees.c.id).where(
        employees.c.organization_id == actor.organization_id, or_(*grants)
    )


@event.listens_for(Session, "do_orm_execute")
def protect_supervised_employees(state):
    actor = state.session.info.get("document_actor")
    if not state.is_select or not is_scoped_supervisor(actor):
        return
    include_self = bool(
        state.session.info.get("employee_self_service")
        or state.execution_options.get("employee_self_service")
    )
    ids = supervised_employee_ids(actor, include_self=include_self)
    options = [with_loader_criteria(Employee, Employee.id.in_(ids), include_aliases=True)]
    related = []
    codes = {p.code for role in scoped_roles(actor) for p in role.permissions}
    for mapper in Base.registry.mappers:
        model = mapper.class_
        # Workforce child lists, salaries, and document search can bypass a
        # parent employee lookup. Apply the boundary to those reads as well.
        if hasattr(model, "employee_id") and model.__tablename__ in {
            "employee_assignments", "employee_family_members", "employee_emergency_contacts",
            "employee_resumes", "employee_documents", "employee_qualifications",
            "employee_skills", "employee_training_records", "employee_licenses",
            "employee_rotations", "employee_asset_authorizations", "time_logs",
            "leave_requests", "employee_salaries", "library_documents",
        }:
            predicate = model.employee_id.in_(ids)
            if model.__tablename__ == "employee_salaries" and "employees.salary.read" not in codes:
                predicate = false()
            if model.__tablename__ == "library_documents":
                predicate = or_(model.employee_id.is_(None),
                                model.employee_id.in_(supervised_employee_ids(actor, include_self=True)),
                                model.owner_id == actor.id)
            options.append(with_loader_criteria(model, predicate, include_aliases=True))
            related.append(model)
    markers = select(ids.subquery().c.id.cast(Text))
    employee_event = or_(
        AuditLog.entity_type == "employee",
        AuditLog.entity_type.like("employee_%"),
        AuditLog.entity_type.in_(["time_log", "leave_request", "salary"]),
        AuditLog.new_values["employee_id"].astext.is_not(None),
        AuditLog.old_values["employee_id"].astext.is_not(None),
    )
    visible_event = [
        and_(AuditLog.entity_type == "employee", AuditLog.entity_id.in_(ids)),
        AuditLog.new_values["employee_id"].astext.in_(markers),
        AuditLog.old_values["employee_id"].astext.in_(markers),
    ]
    # Older assignment events used the employee entity type with an assignment ID.
    for model in related:
        table = model.__table__
        if model.__tablename__ != "library_documents":
            visible_event.append(AuditLog.entity_id.in_(
                select(table.c.id).where(table.c.organization_id == actor.organization_id,
                                         table.c.employee_id.in_(ids))
            ))
    options.append(with_loader_criteria(
        AuditLog, or_(~employee_event, *visible_event), include_aliases=True
    ))
    state.statement = state.statement.options(*options)

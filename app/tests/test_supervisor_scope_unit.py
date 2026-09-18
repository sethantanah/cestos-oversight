"""Exercise ORM enforcement in an isolated in-memory database, without PostgreSQL."""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, aliased

from app.models import Employee, EmployeeAssignment, Role
from app.services.employee_access import is_scoped_supervisor  # registers the request policy


def test_scoped_orm_lists_counts_aliases_and_assignment_expiry():
    engine = create_engine("sqlite://")
    Employee.__table__.create(engine)
    EmployeeAssignment.__table__.create(engine)
    org, actor_id = uuid.uuid4(), uuid.uuid4()
    actor = SimpleNamespace(id=actor_id, organization_id=org, is_superuser=False,
                            roles=[Role(name="Supervisor", organization_id=org, permissions=[])])
    assert is_scoped_supervisor(actor)
    with Session(engine) as session:
        def employee(number, **values):
            row = Employee(organization_id=org, employee_number=number,
                           first_name=number, last_name="Person", **values)
            session.add(row)
            session.flush()
            return row
        supervisor = employee("SUP", user_id=actor_id)
        direct = employee("DIRECT", supervisor_id=supervisor.id)
        assigned = employee("ASSIGNED")
        hidden = employee("HIDDEN")
        assignment = EmployeeAssignment(
            organization_id=org, employee_id=assigned.id, supervisor_id=supervisor.id,
            project_id=uuid.uuid4(), assignment_number="ASN-1", start_date=date.today(), status="ACTIVE",
        )
        session.add(assignment)
        session.commit()
        expected = {direct.id, assigned.id}
        hidden_id, own_id, assignment_id = hidden.id, supervisor.id, assignment.id
        session.info["document_actor"] = actor
        assert set(session.scalars(select(Employee.id))) == expected
        assert session.scalar(select(func.count()).select_from(Employee)) == 2
        alias = aliased(Employee)
        assert set(session.scalars(select(alias.id))) == expected
        assert session.scalar(select(Employee).where(Employee.id == hidden_id)) is None
        assert list(session.scalars(select(EmployeeAssignment.id))) == [assignment_id]
        # Explicit self-service includes only the caller in addition to their team.
        assert session.scalar(select(Employee.id).where(Employee.id == own_id)
                              .execution_options(employee_self_service=True)) == own_id
        assert session.scalar(select(func.count()).select_from(Employee)) == 2
        assignment.end_date = date.today() - timedelta(days=1)
        session.flush()
        assert set(session.scalars(select(Employee.id))) == {direct.id}
        actor.is_superuser = True
        assert session.scalar(select(func.count()).select_from(Employee)) == 4
    engine.dispose()

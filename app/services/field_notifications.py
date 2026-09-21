"""Transactional field alerts shared by the main inbox, portal, and SMTP outbox."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssetAssignment,
    Employee,
    EmployeeAssignment,
    Organization,
    Project,
    Role,
    User,
)
from app.models.employee import EmployeeDocument, LeaveRequest
from app.models.hr import EmailDelivery, Notification
from app.models.maintenance_hse import MaintenanceWorkOrder
from app.models.operational_logs import AssetMaintenanceJob
from app.models.role import Permission, role_permissions, user_roles
from app.services.employee_access import supervised_employee_ids


async def employee_recipients(
    session: AsyncSession,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    if not employee_id:
        return set()
    employee, user = Employee.__table__, User.__table__
    statement = (
        select(user.c.id)
        .join(
            employee,
            or_(
                user.c.id == employee.c.user_id,
                and_(employee.c.user_id.is_(None), user.c.email == employee.c.work_email),
            ),
        )
        .where(
            employee.c.id == employee_id,
            employee.c.organization_id == organization_id,
            employee.c.is_active.is_(True),
            employee.c.archived_at.is_(None),
            user.c.organization_id == organization_id,
            user.c.is_active.is_(True),
            user.c.archived_at.is_(None),
        )
    )
    return set((await session.scalars(statement)).all())


async def supervisor_recipients(
    session: AsyncSession,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    user, role = User.__table__, Role.__table__
    candidates = (
        await session.scalars(
            select(user.c.id)
            .join(
                user_roles,
                user_roles.c.user_id == user.c.id,
            )
            .join(role, role.c.id == user_roles.c.role_id)
            .where(
                user.c.organization_id == organization_id,
                user.c.is_active.is_(True),
                user.c.archived_at.is_(None),
                func.lower(func.trim(role.c.name)) == "supervisor",
                or_(
                    role.c.organization_id == organization_id,
                    and_(role.c.is_system_role.is_(True), role.c.organization_id.is_(None)),
                ),
            )
            .distinct()
        )
    ).all()
    recipients = set()
    for user_id in candidates:
        actor = SimpleNamespace(id=user_id, organization_id=organization_id)
        if employee_id:
            team = supervised_employee_ids(actor).subquery()
            if await session.scalar(select(team.c.id).where(team.c.id == employee_id)):
                recipients.add(user_id)
        elif project_id:
            employee, assignment = Employee.__table__, EmployeeAssignment.__table__
            profiles = select(employee.c.id).where(
                employee.c.user_id == user_id,
                employee.c.organization_id == organization_id,
                employee.c.is_active.is_(True),
                employee.c.archived_at.is_(None),
            )
            if await session.scalar(
                select(assignment.c.id)
                .where(
                    assignment.c.organization_id == organization_id,
                    assignment.c.project_id == project_id,
                    assignment.c.status == "ACTIVE",
                    assignment.c.start_date <= date.today(),
                    or_(assignment.c.end_date.is_(None), assignment.c.end_date >= date.today()),
                    or_(
                        assignment.c.employee_id.in_(profiles),
                        assignment.c.supervisor_id.in_(profiles),
                    ),
                )
                .limit(1)
            ):
                recipients.add(user_id)
    return recipients


async def emit_event(
    session: AsyncSession,
    organization_id: uuid.UUID,
    recipients: set[uuid.UUID],
    event_key: str,
    message: str,
    domain: str,
    kind: str,
    priority: str = "IMPORTANT",
    delivery_method: str = "BOTH",
    schedule_id: uuid.UUID | None = None,
) -> int:
    """Stable primary keys deduplicate concurrent retries, even after read/resolution.

    Both inserts use the caller's transaction. No external email is sent here.
    """
    if not recipients:
        return 0
    user = User.__table__
    eligible = (
        await session.scalars(
            select(user.c.id).where(
                user.c.id.in_(recipients),
                user.c.organization_id == organization_id,
                user.c.is_active.is_(True),
                user.c.archived_at.is_(None),
            )
        )
    ).all()
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    count = 0
    for recipient_id in eligible:
        notification_id = uuid.uuid5(organization_id, f"{event_key}:{recipient_id}")
        created = await session.scalar(
            insert(Notification)
            .values(
                id=notification_id,
                organization_id=organization_id,
                recipient_id=recipient_id,
                message=message[:1000],
                domain=domain,
                priority_tag=priority,
                delivery_method=delivery_method,
                schedule_id=schedule_id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(Notification.id)
        )
        if not created:
            continue
        count += 1
        if delivery_method in {"BOTH", "EMAIL"}:
            await session.execute(
                insert(EmailDelivery)
                .values(
                    id=uuid.uuid5(notification_id, "email"),
                    organization_id=organization_id,
                    recipient_id=recipient_id,
                    kind=kind,
                    message=message[:1000],
                    next_attempt_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
    return count


async def notify_assignment(session: AsyncSession, assignment: EmployeeAssignment) -> int:
    recipients = await employee_recipients(
        session, assignment.organization_id, assignment.employee_id
    )
    project = Project.__table__
    name = await session.scalar(
        select(project.c.name).where(
            project.c.id == assignment.project_id,
            project.c.organization_id == assignment.organization_id,
        )
    )
    message = (
        f"Project assignment {assignment.assignment_number}: {name or 'Project'}. "
        f"Status: {assignment.status}. Role: {assignment.role_on_project or 'Team member'}. "
        f"Starts {assignment.start_date}; ends {assignment.end_date or 'not specified'}."
    )
    return await emit_event(
        session,
        assignment.organization_id,
        recipients,
        f"assignment:{assignment.id}:{assignment.updated_at.isoformat()}",
        message,
        "PROJECTS",
        "PROJECT_ASSIGNMENT",
    )


async def leave_approver_recipients(session, organization_id, employee_id):
    recipients = await supervisor_recipients(session, organization_id, employee_id)
    permitted_roles = select(Role.id).join(role_permissions, role_permissions.c.role_id == Role.id).join(
        Permission, Permission.id == role_permissions.c.permission_id).where(
        Permission.code == "employees.leave.approve",
        or_(Role.organization_id == organization_id,
            and_(Role.is_system_role.is_(True), Role.organization_id.is_(None))))
    recipients.update((await session.scalars(select(User.id).where(
        User.organization_id == organization_id, User.is_active.is_(True), User.archived_at.is_(None),
        or_(User.is_superuser.is_(True), User.id.in_(select(user_roles.c.user_id).where(
            user_roles.c.role_id.in_(permitted_roles))))))).all())
    return recipients


async def notify_leave(session: AsyncSession, leave: LeaveRequest) -> int:
    employee = Employee.__table__
    person = (
        await session.execute(
            select(employee.c.first_name, employee.c.last_name).where(
                employee.c.id == leave.employee_id,
                employee.c.organization_id == leave.organization_id,
            )
        )
    ).first()
    if not person:
        return 0
    if leave.status == "PENDING":
        recipients = await leave_approver_recipients(session, leave.organization_id, leave.employee_id)
        message = (
            f"{person.first_name} {person.last_name} requested {leave.leave_type or 'leave'} "
            f"from {leave.start_date} to {leave.end_date}. "
            "Review the request in leave management or Field Portal > Site Team & Personnel."
        )
        kind = "LEAVE_REQUESTED"
    else:
        recipients = await employee_recipients(session, leave.organization_id, leave.employee_id)
        message = (
            f"Your leave request for {leave.start_date} to {leave.end_date} "
            f"was {leave.status.lower()}."
        )
        kind = "LEAVE_DECISION"
    return await emit_event(
        session,
        leave.organization_id,
        recipients,
        f"leave:{leave.id}:{leave.status}",
        message,
        "WORKFORCE",
        kind,
    )


async def work_supervisors(session: AsyncSession, work: Any) -> set[uuid.UUID]:
    employee_id = getattr(work, "assigned_employee_id", None) or getattr(
        work, "assigned_technician_id", None
    )
    recipients = await supervisor_recipients(
        session, work.organization_id, employee_id, work.project_id
    )
    if not employee_id and not work.project_id:
        assignment = AssetAssignment.__table__
        projects = (
            await session.scalars(
                select(assignment.c.project_id).where(
                    assignment.c.organization_id == work.organization_id,
                    assignment.c.asset_id == work.asset_id,
                    assignment.c.status == "ACTIVE",
                    assignment.c.assigned_at <= datetime.now(UTC),
                    assignment.c.returned_at.is_(None),
                )
            )
        ).all()
        for project_id in projects:
            recipients |= await supervisor_recipients(
                session, work.organization_id, project_id=project_id
            )
    return recipients


async def notify_work_order(session: AsyncSession, work: Any, event: str = "assigned") -> int:
    employee_id = getattr(work, "assigned_employee_id", None) or getattr(
        work, "assigned_technician_id", None
    )
    recipients = await employee_recipients(session, work.organization_id, employee_id)
    if event in {"completed", "cancelled"}:
        recipients |= await work_supervisors(session, work)
    reference = getattr(work, "wo_number", None) or str(work.id)[:8]
    return await emit_event(
        session,
        work.organization_id,
        recipients,
        f"work:{work.__tablename__}:{work.id}:{event}:{work.updated_at.isoformat()}",
        f"Maintenance work order {reference}: {work.title}. {event.capitalize()}. "
        f"Scheduled due date: {work.scheduled_date or 'not specified'}. "
        f"Status: {'APPROVED' if getattr(work, 'approved_at', None) else work.status}.",
        "EQUIPMENT",
        "WORK_ORDER_UPDATE",
    )


def expiry_stage(expiry: date, today: date) -> str | None:
    days = (expiry - today).days
    if days < 0:
        return "expired"
    for threshold in (1, 7, 14, 30):
        if days <= threshold:
            return f"{threshold}d"
    return None


async def generate_field_alerts(session: AsyncSession, today: date | None = None) -> int:
    """Scheduler catch-up: one alert per expiry stage or overdue week, per recipient."""
    today = today or datetime.now(UTC).date()
    total = 0
    organizations = (
        await session.scalars(
            select(Organization.id).where(
                Organization.is_active.is_(True),
            )
        )
    ).all()
    for org_id in organizations:
        total += await generate_people_alerts(session, org_id, today)
        people = (
            await session.scalars(
                select(Employee).where(
                    Employee.organization_id == org_id,
                    Employee.is_active.is_(True),
                    Employee.archived_at.is_(None),
                )
            )
        ).all()
        expiries = {
            (person.id, person.contract_end_date) for person in people if person.contract_end_date
        }
        documents = (
            await session.scalars(
                select(EmployeeDocument).where(
                    EmployeeDocument.organization_id == org_id,
                    EmployeeDocument.document_type == "EMPLOYMENT_CONTRACT",
                    EmployeeDocument.is_active.is_(True),
                    EmployeeDocument.verification_status != "REJECTED",
                    EmployeeDocument.expiry_date.is_not(None),
                )
            )
        ).all()
        person_ids = {person.id for person in people}
        expiries |= {
            (doc.employee_id, doc.expiry_date) for doc in documents if doc.employee_id in person_ids
        }
        for employee_id, expiry in expiries:
            if not expiry or not (stage := expiry_stage(expiry, today)):
                continue
            person = next(person for person in people if person.id == employee_id)
            recipients = await employee_recipients(session, org_id, employee_id)
            recipients |= await supervisor_recipients(session, org_id, employee_id)
            total += await emit_event(
                session,
                org_id,
                recipients,
                f"contract:{employee_id}:{expiry}:{stage}",
                f"Employment contract for {person.first_name} {person.last_name} "
                f"{'expired' if expiry < today else 'expires'} on {expiry}. "
                "Contact HR to review renewal arrangements.",
                "WORKFORCE",
                "CONTRACT_EXPIRY",
                "CRITICAL" if expiry < today else "IMPORTANT",
            )
        for model in (AssetMaintenanceJob, MaintenanceWorkOrder):
            query = select(model).where(
                model.organization_id == org_id,
                model.status.in_(["OPEN", "IN_PROGRESS", "WAITING_PARTS"]),
                model.scheduled_date.is_not(None),
                model.scheduled_date <= today + timedelta(days=1),
            )
            if model is MaintenanceWorkOrder:
                query = query.where(model.archived_at.is_(None), model.is_active.is_(True))
            for work in (await session.scalars(query)).all():
                employee_id = getattr(work, "assigned_employee_id", None) or getattr(
                    work, "assigned_technician_id", None
                )
                recipients = await employee_recipients(session, org_id, employee_id)
                overdue = work.scheduled_date < today
                if overdue:
                    recipients |= await work_supervisors(session, work)
                stage = (
                    f"overdue-week-{(today - work.scheduled_date).days // 7}" if overdue else "due"
                )
                total += await emit_event(
                    session,
                    org_id,
                    recipients,
                    f"work-due:{model.__tablename__}:{work.id}:{work.scheduled_date}:{stage}",
                    f"Maintenance work order '{work.title}' "
                    f"is {'overdue' if overdue else 'due soon'} "
                    f"(scheduled due {work.scheduled_date}); current status: {work.status}.",
                    "EQUIPMENT",
                    "WORK_ORDER_OVERDUE" if overdue else "WORK_ORDER_DUE",
                    "CRITICAL" if overdue else "IMPORTANT",
                )
    await session.commit()
    return total


async def notify_training(session, training, *, changed=False):
    recipients = await employee_recipients(session, training.organization_id, training.employee_id)
    state = str(training.status)
    key = f"training:{training.id}:{training.updated_at if changed else 'created'}:{state}"
    action = "updated" if changed else "planned"
    return await emit_event(session, training.organization_id, recipients, key,
        f"Training '{training.training_name}' has been {action} for you. "
        f"Start: {training.start_date or 'to be confirmed'}. Provider: {training.provider or 'to be confirmed'}. "
        f"Status: {state.replace('_', ' ').lower()}.", "WORKFORCE", "TRAINING_UPDATED" if changed else "TRAINING_PLANNED")


async def generate_people_alerts(session, org_id, today):
    """Catch up events and send bounded leave/training reminders without duplicate delivery."""
    from app.models.employee import EmployeeTrainingRecord
    total = 0
    leaves = (await session.scalars(select(LeaveRequest).where(
        LeaveRequest.organization_id == org_id, LeaveRequest.end_date >= today))).all()
    for leave in leaves:
        total += await notify_leave(session, leave)
        if leave.status == "PENDING":
            age = (today - leave.created_at.date()).days
            if age < 2:
                continue
            recipients = await leave_approver_recipients(session, org_id, leave.employee_id)
            stage = f"pending-week-{age // 7}"
            message = f"Leave request for {leave.start_date} to {leave.end_date} is still awaiting approval. Review the pending leave requests."
        elif leave.status == "APPROVED" and today <= leave.start_date <= today + timedelta(days=7):
            recipients = await employee_recipients(session, org_id, leave.employee_id)
            recipients |= await supervisor_recipients(session, org_id, leave.employee_id)
            stage = expiry_stage(leave.start_date, today)
            message = f"Approved leave starts on {leave.start_date} and ends on {leave.end_date}. Please prepare the handover."
        else:
            continue
        total += await emit_event(session, org_id, recipients, f"leave-reminder:{leave.id}:{leave.start_date}:{stage}", message, "WORKFORCE", "LEAVE_REMINDER")
    records = (await session.scalars(select(EmployeeTrainingRecord).where(
        EmployeeTrainingRecord.organization_id == org_id,
        EmployeeTrainingRecord.is_active.is_(True), EmployeeTrainingRecord.archived_at.is_(None),
        EmployeeTrainingRecord.status.in_(["PLANNED", "IN_PROGRESS", "COMPLETED", "EXPIRED"])))).all()
    for training in records:
        recipients = await employee_recipients(session, org_id, training.employee_id)
        if training.status in {"PLANNED", "IN_PROGRESS"}:
            total += await notify_training(session, training)
            if training.start_date and today <= training.start_date <= today + timedelta(days=7):
                stage = expiry_stage(training.start_date, today)
                total += await emit_event(session, org_id, recipients,
                    f"training-due:{training.id}:{training.start_date}:{stage}",
                    f"Reminder: '{training.training_name}' starts on {training.start_date}. Provider: {training.provider or 'to be confirmed'}.",
                    "WORKFORCE", "TRAINING_DUE")
        elif training.expiry_date:
            stage = expiry_stage(training.expiry_date, today)
            if stage:
                recipients |= await supervisor_recipients(session, org_id, training.employee_id)
                total += await emit_event(session, org_id, recipients,
                    f"training-expiry:{training.id}:{training.expiry_date}:{stage}",
                    f"Training certificate '{training.training_name}' expires on {training.expiry_date}. Arrange renewal or recertification.",
                    "WORKFORCE", "TRAINING_EXPIRY")
    return total

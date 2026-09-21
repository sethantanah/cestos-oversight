"""Evaluate saved schedules against real due dates and run them independently."""

import calendar
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, func, or_, select

from app.core.dependencies import scoped_roles
from app.core.exceptions import ValidationError
from app.models import Asset, Employee, Organization, Project, Role, User
from app.models.employee import EmployeeDocument, EmployeeRotation, EmployeeTrainingRecord, LeaveRequest
from app.models.hr import NotificationSchedule
from app.models.inventory import InventoryBalance, InventoryItem, InventoryLot
from app.models.maintenance_hse import MaintenanceWorkOrder
from app.models.operational_logs import AssetMaintenanceJob
from app.models.role import user_roles
from app.services.field_notifications import emit_event

RULES = {
    "WORKFORCE_DOCUMENT_EXPIRY": "WORKFORCE",
    "WORKFORCE_ROTATION_DUE": "WORKFORCE",
    "WORKFORCE_LEAVE_PENDING": "WORKFORCE",
    "WORKFORCE_LEAVE_UPCOMING": "WORKFORCE",
    "WORKFORCE_TRAINING_DUE": "WORKFORCE",
    "WORKFORCE_TRAINING_EXPIRY": "WORKFORCE",
    "WORKFORCE_CONTRACT_EXPIRY": "WORKFORCE",
    "INVENTORY_CONSUMABLES_EXPIRY": "INVENTORY",
    "INVENTORY_LOW_STOCK": "INVENTORY",
    "EQUIPMENT_MAINTENANCE_DUE": "EQUIPMENT",
    "EQUIPMENT_STATUS_CHANGE": "EQUIPMENT",
    "PROJECT_MILESTONE_DUE": "PROJECTS",
}
FREQUENCIES = {
    "ONCE": 0,
    "DAILY": 1,
    "EVERY_OTHER_DAY": 2,
    "WEEKLY": 7,
    "BIWEEKLY": 14,
    "MONTHLY": 0,
}


def allowed_domains(actor):
    if actor.is_superuser:
        return {"WORKFORCE", "INVENTORY", "EQUIPMENT", "PROJECTS"}
    codes = {permission.code for role in scoped_roles(actor) for permission in role.permissions}
    domain_permissions = {
        "WORKFORCE": {"employees.alerts.manage"},
        "INVENTORY": {"inventory.manage", "inventory.admin", "inventory.write"},
        "EQUIPMENT": {"assets.update", "assets.manage", "assets.write"},
        "PROJECTS": {"projects.update", "projects.manage", "projects.write"},
    }
    return {domain for domain, permissions in domain_permissions.items() if codes & permissions}


def validate_schedule(schedule):
    if RULES.get(schedule.rule_type) != schedule.domain:
        raise ValidationError("Unsupported notification rule or domain mismatch")
    if schedule.frequency not in FREQUENCIES:
        raise ValidationError("Unsupported notification frequency")
    if schedule.delivery_method not in {"BOTH", "EMAIL", "ON_PLATFORM"}:
        raise ValidationError("Unsupported delivery method")
    if not 0 <= schedule.lead_time_days <= 365:
        raise ValidationError("Lead time must be between 0 and 365 days")


def next_run(now, frequency):
    if frequency == "ONCE":
        return None
    if frequency == "MONTHLY":
        year, month = now.year + now.month // 12, now.month % 12 + 1
        return now.replace(
            year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
        )
    return now + timedelta(days=FREQUENCIES[frequency])


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


async def recipients(session, schedule):
    ids = {uuid.UUID(str(value)) for value in (schedule.recipient_user_ids or [])}
    # Older UI versions saved employee IDs into recipient_user_ids. Resolve those
    # to their linked account without broadening to the schedule owner or other staff.
    from app.services.field_notifications import employee_recipients

    for selected_id in tuple(ids):
        ids.update(await employee_recipients(session, schedule.organization_id, selected_id))
    roles = {name.strip().casefold() for name in (schedule.recipient_roles or [])}
    # Default to the schedule owner only when no recipient selection was made.
    if not ids and not roles:
        ids.add(schedule.created_by_id)
    if roles:
        selected = (
            select(user_roles.c.user_id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                func.lower(func.trim(Role.name)).in_(roles),
                or_(
                    Role.organization_id == schedule.organization_id,
                    and_(Role.is_system_role.is_(True), Role.organization_id.is_(None)),
                ),
            )
        )
        ids.update((await session.scalars(selected)).all())
    return set(
        (
            await session.scalars(
                select(User.id).where(
                    User.id.in_(ids),
                    User.organization_id == schedule.organization_id,
                    User.is_active.is_(True),
                    User.archived_at.is_(None),
                )
            )
        ).all()
    )


async def matching_alerts(session, schedule, today):
    org = schedule.organization_id
    cutoff = today + timedelta(days=schedule.lead_time_days)
    rule = schedule.rule_type
    alerts = []
    if rule == "WORKFORCE_DOCUMENT_EXPIRY":
        rows = (
            await session.execute(
                select(EmployeeDocument, Employee)
                .join(Employee, Employee.id == EmployeeDocument.employee_id)
                .where(
                    EmployeeDocument.organization_id == org,
                    Employee.organization_id == org,
                    EmployeeDocument.is_active.is_(True),
                    EmployeeDocument.archived_at.is_(None),
                    EmployeeDocument.verification_status != "REJECTED",
                    EmployeeDocument.expiry_date <= cutoff,
                    Employee.is_active.is_(True),
                    Employee.archived_at.is_(None),
                )
            )
        ).all()
        for doc, employee in rows:
            days = (doc.expiry_date - today).days
            timing = f"expires in {days} days" if days >= 0 else f"expired {-days} days ago"
            alerts.append(
                (
                    str(doc.id),
                    f"{doc.title} ({doc.document_type}) for "
                    f"{employee.first_name} {employee.last_name} ({employee.employee_number}) "
                    f"{timing}, on {doc.expiry_date.isoformat()}.",
                )
            )
    elif rule == "WORKFORCE_ROTATION_DUE":
        rows = (
            await session.execute(
                select(EmployeeRotation, Employee)
                .join(Employee, Employee.id == EmployeeRotation.employee_id)
                .where(
                    EmployeeRotation.organization_id == org,
                    Employee.organization_id == org,
                    EmployeeRotation.status.in_(["PLANNED", "ON_SITE"]),
                    EmployeeRotation.work_end_date.between(today, cutoff),
                    Employee.is_active.is_(True),
                    Employee.archived_at.is_(None),
                )
            )
        ).all()
        for rotation, employee in rows:
            alerts.append(
                (
                    str(rotation.id),
                    f"Rotation for {employee.first_name} {employee.last_name} "
                    f"ends on {rotation.work_end_date.isoformat()}.",
                )
            )
    elif rule == "INVENTORY_CONSUMABLES_EXPIRY":
        stock = (
            select(func.coalesce(func.sum(InventoryBalance.quantity_on_hand), 0))
            .where(
                InventoryBalance.organization_id == org,
                InventoryBalance.lot_id == InventoryLot.id,
            )
            .correlate(InventoryLot)
            .scalar_subquery()
        )
        rows = (
            await session.execute(
                select(InventoryLot, InventoryItem)
                .join(InventoryItem, InventoryItem.id == InventoryLot.item_id)
                .where(
                    InventoryLot.organization_id == org,
                    InventoryItem.organization_id == org,
                    InventoryLot.status == "ACTIVE",
                    InventoryItem.is_active.is_(True),
                    InventoryLot.expiry_date <= cutoff,
                    stock > 0,
                )
            )
        ).all()
        for lot, item in rows:
            alerts.append(
                (
                    str(lot.id),
                    f"Inventory lot {lot.lot_number} for {item.name} "
                    f"has expiry date {lot.expiry_date.isoformat()}.",
                )
            )
    elif rule == "INVENTORY_LOW_STOCK":
        stock = (
            select(func.coalesce(func.sum(InventoryBalance.quantity_on_hand), 0))
            .where(
                InventoryBalance.organization_id == org,
                InventoryBalance.item_id == InventoryItem.id,
            )
            .correlate(InventoryItem)
            .scalar_subquery()
        )
        rows = (
            await session.execute(
                select(InventoryItem, stock).where(
                    InventoryItem.organization_id == org,
                    InventoryItem.is_active.is_(True),
                    stock <= InventoryItem.reorder_point,
                )
            )
        ).all()
        for item, quantity in rows:
            alerts.append(
                (
                    str(item.id),
                    f"Low stock: {item.name} ({item.sku or item.item_number}) "
                    f"has {quantity} remaining; reorder point {item.reorder_point}.",
                )
            )
    elif rule == "EQUIPMENT_MAINTENANCE_DUE":
        rows = (
            await session.scalars(
                select(AssetMaintenanceJob).where(
                    AssetMaintenanceJob.organization_id == org,
                    AssetMaintenanceJob.status.in_(["OPEN", "IN_PROGRESS"]),
                    AssetMaintenanceJob.scheduled_date <= cutoff,
                )
            )
        ).all()
        rows += (
            await session.scalars(
                select(MaintenanceWorkOrder).where(
                    MaintenanceWorkOrder.organization_id == org,
                    MaintenanceWorkOrder.is_active.is_(True),
                    MaintenanceWorkOrder.archived_at.is_(None),
                    MaintenanceWorkOrder.status.in_(["OPEN", "IN_PROGRESS", "WAITING_PARTS"]),
                    MaintenanceWorkOrder.scheduled_date <= cutoff,
                )
            )
        ).all()
        for job in rows:
            alerts.append(
                (
                    str(job.id),
                    f"Maintenance {job.title} is {job.status}; "
                    f"due on {job.scheduled_date.isoformat()}.",
                )
            )
    elif rule == "EQUIPMENT_STATUS_CHANGE":
        rows = (
            await session.scalars(
                select(Asset).where(
                    Asset.organization_id == org,
                    Asset.is_active.is_(True),
                    Asset.archived_at.is_(None),
                    Asset.status.in_(["BREAKDOWN", "UNDER_MAINTENANCE", "QUARANTINED"]),
                )
            )
        ).all()
        for asset in rows:
            alerts.append(
                (
                    str(asset.id),
                    f"Equipment {asset.name} ({asset.asset_number}) has status {asset.status}.",
                )
            )
    elif rule == "PROJECT_MILESTONE_DUE":
        rows = (
            await session.scalars(
                select(Project).where(
                    Project.organization_id == org,
                    Project.is_active.is_(True),
                    Project.archived_at.is_(None),
                    Project.status.in_(["ACTIVE", "MOBILIZING"]),
                    Project.actual_end_date.is_(None),
                    Project.expected_end_date <= cutoff,
                )
            )
        ).all()
        for project in rows:
            alerts.append(
                (
                    str(project.id),
                    f"Project {project.name} has expected end date "
                    f"{project.expected_end_date.isoformat()}.",
                )
            )
    if rule in {"WORKFORCE_LEAVE_PENDING", "WORKFORCE_LEAVE_UPCOMING"}:
        query = select(LeaveRequest).where(LeaveRequest.organization_id == org,
            LeaveRequest.end_date >= today,
            LeaveRequest.status == ("PENDING" if rule.endswith("PENDING") else "APPROVED"))
        if rule.endswith("UPCOMING"):
            query = query.where(LeaveRequest.start_date >= today, LeaveRequest.start_date <= cutoff)
        for leave in (await session.scalars(query)).all():
            alerts.append((str(leave.id), f"Leave request {leave.id} ({leave.start_date} to {leave.end_date}) is {leave.status.lower()}."))
    elif rule in {"WORKFORCE_TRAINING_DUE", "WORKFORCE_TRAINING_EXPIRY"}:
        upcoming = rule.endswith("DUE")
        due_date = EmployeeTrainingRecord.start_date if upcoming else EmployeeTrainingRecord.expiry_date
        query = select(EmployeeTrainingRecord).where(EmployeeTrainingRecord.organization_id == org,
            EmployeeTrainingRecord.is_active.is_(True), EmployeeTrainingRecord.archived_at.is_(None),
            EmployeeTrainingRecord.status.in_(["PLANNED", "IN_PROGRESS"] if upcoming else ["COMPLETED", "EXPIRED"]),
            due_date <= cutoff)
        if upcoming:
            query = query.where(due_date >= today)
        for training in (await session.scalars(query)).all():
            alerts.append((str(training.id), f"Training '{training.training_name}' {'starts' if upcoming else 'expires'} on {training.start_date if upcoming else training.expiry_date}."))
    elif rule == "WORKFORCE_CONTRACT_EXPIRY":
        for employee in (await session.scalars(select(Employee).where(Employee.organization_id == org,
            Employee.is_active.is_(True), Employee.archived_at.is_(None), Employee.contract_end_date <= cutoff))).all():
            alerts.append((str(employee.id), f"Employment contract for {employee.first_name} {employee.last_name} ends on {employee.contract_end_date}."))
    return alerts


async def evaluate(session, schedule, now=None):
    if not schedule.is_active:
        return 0
    validate_schedule(schedule)
    now = now or datetime.now(UTC)
    targets = await recipients(session, schedule)
    if not targets:
        raise ValidationError("Schedule has no active recipients in this organization")
    # Manual reruns in the same interval repair missing events without duplicate delivery.
    current_period = bool(
        schedule.last_run_at
        and (
            schedule.frequency == "ONCE"
            or (schedule.next_run_at and utc(schedule.next_run_at) > now)
        )
    )
    period = utc(schedule.last_run_at) if current_period else now
    count = 0
    for entity_id, message in await matching_alerts(session, schedule, now.date()):
        count += await emit_event(
            session,
            schedule.organization_id,
            targets,
            f"schedule:{schedule.id}:{period.isoformat()}:{entity_id}",
            f"[{schedule.priority_tag}] {schedule.title}: {message}",
            schedule.domain,
            "SCHEDULED_ALERT",
            schedule.priority_tag,
            schedule.delivery_method,
            schedule_id=schedule.id,
        )
    if not current_period:
        schedule.last_run_at = now
        schedule.next_run_at = next_run(now, schedule.frequency)
    await session.commit()
    return count


async def run_due_schedules(session_factory, now=None):
    now = now or datetime.now(UTC)
    due = and_(
        NotificationSchedule.is_active.is_(True),
        or_(
            NotificationSchedule.last_run_at.is_(None),
            and_(
                NotificationSchedule.frequency != "ONCE",
                or_(
                    NotificationSchedule.next_run_at.is_(None),
                    NotificationSchedule.next_run_at <= now,
                ),
            ),
        ),
    )
    async with session_factory() as session:
        ids = (
            await session.scalars(
                select(NotificationSchedule.id)
                .join(Organization, Organization.id == NotificationSchedule.organization_id)
                .where(due, Organization.is_active.is_(True))
            )
        ).all()
    total = 0
    for schedule_id in ids:
        try:
            async with session_factory() as session:
                schedule = await session.scalar(
                    select(NotificationSchedule)
                    .where(NotificationSchedule.id == schedule_id, due)
                    .with_for_update(skip_locked=True)
                )
                if schedule:
                    total += await evaluate(session, schedule, now)
        except Exception:
            structlog.get_logger().exception(
                "notification_schedule_failed", schedule_id=str(schedule_id)
            )
    return total

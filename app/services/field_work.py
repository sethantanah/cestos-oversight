"""Field work is visible to its explicit assignee; supervisors review their team."""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.core.dependencies import scoped_roles
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Asset, Employee
from app.models.maintenance_hse import MaintenanceWorkOrder
from app.models.operational_logs import AssetMaintenanceJob
from app.services.employee_access import supervised_employee_ids


def is_supervisor(actor):
    return any(role.name.strip().casefold() == "supervisor" for role in scoped_roles(actor))


def own_employee_ids(actor):
    employee = Employee.__table__
    return select(employee.c.id).where(
        employee.c.organization_id == actor.organization_id,
        employee.c.user_id == actor.id,
        employee.c.is_active.is_(True),
        employee.c.archived_at.is_(None),
    )


class FieldWorkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = Field(default=None, max_length=100)
    completed: bool | None = None
    note: str | None = Field(default=None, min_length=1, max_length=5000)
    status: Literal["IN_PROGRESS", "COMPLETED", "APPROVED"] | None = None


class FieldWorkEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    maintenance_type: Literal[
        "PREVENTIVE", "CORRECTIVE", "INSPECTION", "SERVICE", "OTHER", "EMERGENCY", "OVERHAUL"
    ]
    priority: Literal["LOW", "NORMAL", "MEDIUM", "HIGH", "CRITICAL"]
    scheduled_date: date | None = None
    assigned_employee_id: uuid.UUID
    is_recurring: bool = False
    recurrence_interval_days: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def recurrence_requires_interval(self):
        if self.is_recurring and self.recurrence_interval_days is None:
            raise ValueError("Recurring maintenance requires an interval in days")
        return self


def public_job(job, asset_name=None):
    return dict(
        id=job.id,
        source="maintenance_job" if isinstance(job, AssetMaintenanceJob) else "work_order",
        is_recurring=getattr(job, "is_recurring", False),
        recurrence_interval_days=getattr(job, "recurrence_interval_days", None),
        asset_id=job.asset_id,
        project_id=job.project_id,
        title=job.title,
        description=job.description,
        priority=job.priority,
        maintenance_type=getattr(job, "maintenance_type", None) or getattr(job, "work_type", None),
        scheduled_date=job.scheduled_date,
        assigned_employee_id=getattr(job, "assigned_employee_id", None)
        or getattr(job, "assigned_technician_id", None),
        status="APPROVED" if job.approved_at else job.status,
        checklist=job.checklist or [],
        notes=job.field_notes
        or getattr(job, "completion_notes", None)
        or getattr(job, "notes", None)
        or "",
        completed_at=job.completed_at,
        completion_notes=getattr(job, "completion_notes", None) or job.field_notes or "",
        approved_at=job.approved_at,
        asset_name=asset_name,
    )


async def list_work(session, actor, project_id=None, planning=False):
    if planning and not is_supervisor(actor):
        raise ForbiddenError("Only supervisors can access Planning")
    employee_ids = (
        supervised_employee_ids(actor, include_self=True) if planning else own_employee_ids(actor)
    )
    own_ids = set((await session.scalars(own_employee_ids(actor))).all())
    employee = Employee.__table__.alias("field_assignee")
    result = []
    for model, assignee in [
        (AssetMaintenanceJob, AssetMaintenanceJob.assigned_employee_id),
        (MaintenanceWorkOrder, MaintenanceWorkOrder.assigned_technician_id),
    ]:
        query = (
            select(model, Asset.name, employee.c.first_name, employee.c.last_name)
            .join(Asset, Asset.id == model.asset_id)
            .join(
                employee,
                (employee.c.id == assignee) & (employee.c.organization_id == actor.organization_id),
            )
            .where(
                model.organization_id == actor.organization_id,
                Asset.organization_id == actor.organization_id,
                assignee.in_(employee_ids),
            )
        )
        if model is MaintenanceWorkOrder:
            query = query.where(model.is_active.is_(True), model.archived_at.is_(None))
        if project_id:
            query = query.where(model.project_id == project_id)
        result.extend(
            dict(public_job(job, name), assigned_to=f"{first_name} {last_name}".strip())
            for job, name, first_name, last_name in (
                await session.execute(query.order_by(model.scheduled_date, model.id))
            ).all()
        )
    for item in result:
        item["can_update"] = item["assigned_employee_id"] in own_ids
        item["can_reassign"] = is_supervisor(actor)
        item["can_edit"] = is_supervisor(actor) and item["status"] not in {
            "COMPLETED",
            "APPROVED",
            "CANCELLED",
        }
    return result


async def _work_access(session, actor, job_id):
    job = await session.scalar(
        select(AssetMaintenanceJob)
        .where(
            AssetMaintenanceJob.id == job_id,
            AssetMaintenanceJob.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not job:
        job = await session.scalar(
            select(MaintenanceWorkOrder)
            .where(
                MaintenanceWorkOrder.id == job_id,
                MaintenanceWorkOrder.organization_id == actor.organization_id,
                MaintenanceWorkOrder.is_active.is_(True),
                MaintenanceWorkOrder.archived_at.is_(None),
            )
            .with_for_update()
        )
    if not job:
        raise NotFoundError("Work order not found")
    employee_id = getattr(job, "assigned_employee_id", None) or getattr(
        job, "assigned_technician_id", None
    )
    supervisor = is_supervisor(actor)
    own = await session.scalar(
        own_employee_ids(actor).where(Employee.__table__.c.id == employee_id)
    )
    can_review = supervisor and await session.scalar(
        select(Employee.id).where(
            Employee.id == employee_id,
            Employee.id.in_(supervised_employee_ids(actor, include_self=True)),
        )
    )
    if not own and not can_review:
        raise NotFoundError("Work order not found")
    return job, bool(own), bool(can_review)


async def update_work(session, actor, job_id, body, *, commit=True):
    job, own, can_review = await _work_access(session, actor, job_id)
    supervisor = is_supervisor(actor)
    if body.status == "APPROVED":
        if not supervisor or not can_review:
            raise ForbiddenError("Only the team supervisor can approve completed work")
        if job.status != "COMPLETED":
            raise ConflictError("Complete the work order before supervisor approval")
        if body.task_id is not None:
            raise ConflictError("Checklist cannot change during approval")
        if job.approved_at:
            return public_job(job)
        job.approved_at = datetime.now(UTC)
        job.approved_by_id = actor.id
    else:
        if not own:
            raise ForbiddenError("Only the explicitly assigned employee can update this work")
        if job.approved_at or job.status in {"COMPLETED", "CANCELLED"}:
            raise ConflictError("Completed or approved work cannot be edited")
        if body.task_id is not None:
            if body.completed is None or not any(
                item["id"] == body.task_id for item in job.checklist or []
            ):
                raise ConflictError("Select an existing checklist task and completion value")
            job.checklist = [
                dict(item, completed=body.completed) if item["id"] == body.task_id else item
                for item in job.checklist or []
            ]
        if body.status == "COMPLETED":
            if any(not task.get("completed") for task in job.checklist or []):
                raise ConflictError("Complete every checklist task before submitting for approval")
            job.completed_at = datetime.now(UTC)
            if isinstance(job, AssetMaintenanceJob):
                job.completion_notes = body.note
        if body.status:
            job.status = body.status
            if body.status == "IN_PROGRESS" and not job.started_at:
                job.started_at = datetime.now(UTC)
    if body.note and body.note.strip():
        job.field_notes = "\n".join(
            filter(
                None,
                [
                    job.field_notes
                    or getattr(job, "completion_notes", None)
                    or getattr(job, "notes", None),
                    f"[{datetime.now(UTC).isoformat()}] {body.note.strip()}",
                ],
            )
        )
    job.updated_by_id = actor.id
    job.updated_at = datetime.now(UTC)
    if body.status:
        from app.services.field_notifications import notify_work_order

        await notify_work_order(session, job, body.status.lower())
    if commit:
        await session.commit()
    return public_job(job)


async def edit_work(session, actor, job_id, body: FieldWorkEdit):
    # Lock before testing status so concurrent completion cannot race the edit.
    job, own, can_review = await _work_access(session, actor, job_id)
    if not is_supervisor(actor) or not can_review:
        raise ForbiddenError("Only the team supervisor can edit work details")
    if job.approved_at or job.status in {"COMPLETED", "APPROVED", "CANCELLED"}:
        raise ConflictError("Completed, approved or cancelled work cannot be edited")
    assignee_field = (
        "assigned_employee_id" if isinstance(job, AssetMaintenanceJob) else "assigned_technician_id"
    )
    old_assignee = getattr(job, assignee_field)
    if body.assigned_employee_id != old_assignee:
        if not can_review:
            raise ForbiddenError("Only the team supervisor can reassign work")
        permitted = await session.scalar(
            select(Employee.id).where(
                Employee.id == body.assigned_employee_id,
                Employee.organization_id == actor.organization_id,
                Employee.is_active.is_(True),
                Employee.archived_at.is_(None),
                Employee.id.in_(supervised_employee_ids(actor, include_self=True)),
            )
        )
        if not permitted:
            raise ForbiddenError("Select an active employee from your supervised team")
    detailed = isinstance(job, MaintenanceWorkOrder)
    allowed_types = (
        {"PREVENTIVE", "CORRECTIVE", "EMERGENCY", "OVERHAUL"}
        if detailed
        else {"PREVENTIVE", "CORRECTIVE", "INSPECTION", "SERVICE", "OTHER"}
    )
    if body.maintenance_type not in allowed_types:
        raise ValidationError("Invalid maintenance type for this work record")
    if body.priority not in (
        {"LOW", "MEDIUM", "HIGH", "CRITICAL"} if detailed else {"LOW", "NORMAL", "HIGH", "CRITICAL"}
    ):
        raise ValidationError("Invalid priority for this work record")
    if detailed and body.is_recurring:
        raise ValidationError("Recurrence is available only for maintenance schedules")
    job.title = body.title
    job.description = body.description
    job.priority = body.priority
    job.scheduled_date = body.scheduled_date
    setattr(job, "work_type" if detailed else "maintenance_type", body.maintenance_type)
    setattr(job, assignee_field, body.assigned_employee_id)
    if not detailed:
        job.is_recurring = body.is_recurring
        job.recurrence_interval_days = body.recurrence_interval_days if body.is_recurring else None
    job.updated_by_id = actor.id
    job.updated_at = datetime.now(UTC)
    from app.services.field_notifications import notify_work_order

    await notify_work_order(session, job, "updated")
    await session.commit()
    return public_job(job)

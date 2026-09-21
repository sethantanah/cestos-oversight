"""Field portal reads with explicit role and team boundaries."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, scoped_roles
from app.core.exceptions import ForbiddenError
from app.db.session import get_session
from app.models import Employee, EmployeeAssignment, User
from app.models.employee import AssignmentStatus, LeaveRequest
from app.schemas.drilling import DrillingShiftReportResponse
from app.schemas.operational_logs import FuelLogCreate, FuelReductionCreate, MaintenanceCreate
from app.services.employee_access import supervised_employee_ids
from app.services.field_consumables import ConsumptionCreate
from app.services.field_shifts import FieldShiftEdit
from app.services.field_work import FieldWorkEdit, FieldWorkUpdate

router = APIRouter(prefix="/field-portal", tags=["Field portal"])


class TeamLeaveRead(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    employee_number: str
    job_title: str | None
    leave_type: str | None
    start_date: date
    end_date: date
    days: int
    status: str
    reason: str | None
    notes: str | None
    created_at: datetime
    approved_at: datetime | None
    has_attachment: bool


async def require_supervisor(actor: User = Depends(get_current_active_user)) -> User:
    if not any(role.name.strip().casefold() == "supervisor" for role in scoped_roles(actor)):
        raise ForbiddenError("Only users with the Supervisor role can perform this action")
    return actor


@router.get("/team-leave-requests", response_model=list[TeamLeaveRead])
async def team_leave_requests(
    project_id: uuid.UUID | None = None,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
) -> list[TeamLeaveRead]:
    query = (
        select(LeaveRequest, Employee)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .where(
            LeaveRequest.organization_id == actor.organization_id,
            Employee.organization_id == actor.organization_id,
            Employee.is_active.is_(True),
            Employee.archived_at.is_(None),
            Employee.id.in_(supervised_employee_ids(actor)),
        )
        .order_by(LeaveRequest.created_at.desc(), LeaveRequest.id)
    )
    if project_id is not None:
        current_team = select(EmployeeAssignment.employee_id).where(
            EmployeeAssignment.organization_id == actor.organization_id,
            EmployeeAssignment.project_id == project_id,
            EmployeeAssignment.status == AssignmentStatus.ACTIVE,
            EmployeeAssignment.start_date <= date.today(),
            or_(EmployeeAssignment.end_date.is_(None), EmployeeAssignment.end_date >= date.today()),
        )
        query = query.where(Employee.id.in_(current_team))
    results = await session.execute(query)
    return [
        TeamLeaveRead(
            id=leave.id,
            employee_id=employee.id,
            employee_name=f"{employee.first_name} {employee.last_name}".strip(),
            employee_number=employee.employee_number,
            job_title=employee.job_title,
            leave_type=leave.leave_type,
            start_date=leave.start_date,
            end_date=leave.end_date,
            days=(leave.end_date - leave.start_date).days + 1,
            status=leave.status,
            reason=leave.reason,
            notes=leave.notes,
            created_at=leave.created_at,
            approved_at=leave.approved_at,
            has_attachment=bool(leave.attachment_url),
        )
        for leave, employee in results.all()
    ]


@router.get("/work-orders")
async def field_work_orders(
    project_id: uuid.UUID | None = None,
    planning: bool = False,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_work import list_work

    return await list_work(session, actor, project_id, planning)


@router.patch("/work-orders/{job_id}")
async def update_field_work_order(
    job_id: uuid.UUID,
    body: FieldWorkUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_work import update_work

    return await update_work(session, actor, job_id, body)


@router.patch("/work-orders/{job_id}/details")
async def edit_field_work_order(
    job_id: uuid.UUID,
    body: FieldWorkEdit,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_work import edit_work

    return await edit_work(session, actor, job_id, body)


@router.post("/assets/{asset_id}/work-orders", status_code=201)
async def create_field_work_order(
    asset_id: uuid.UUID,
    body: MaintenanceCreate,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.api.v1.endpoints.operational_logs import create_maintenance

    return await create_maintenance(asset_id, body, actor, session)


async def require_field_employee(
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    from app.services.field_work import own_employee_ids

    if not await session.scalar(own_employee_ids(actor)):
        raise ForbiddenError("An active employee profile is required to log field fuel")
    return actor


@router.post("/assets/{asset_id}/fuel-logs", status_code=201)
async def field_fuel_refill(
    asset_id: uuid.UUID,
    body: FuelLogCreate,
    actor: User = Depends(require_field_employee),
    session: AsyncSession = Depends(get_session),
):
    from app.api.v1.endpoints.operational_logs import create_fuel_log

    return await create_fuel_log(asset_id, body, actor, session)


@router.post("/assets/{asset_id}/fuel-reductions", status_code=201)
async def field_tank_dip(
    asset_id: uuid.UUID,
    body: FuelReductionCreate,
    actor: User = Depends(require_field_employee),
    session: AsyncSession = Depends(get_session),
):
    from app.api.v1.endpoints.operational_logs import create_fuel_reduction

    return await create_fuel_reduction(asset_id, body, actor, session)


@router.get("/projects")
async def field_projects(
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.models import Project
    from app.services.field_equipment import assigned_project_ids

    rows = (
        await session.execute(
            select(Project.id, Project.name, Project.project_number.label("code"))
            .where(Project.id.in_(assigned_project_ids(actor)))
            .order_by(Project.name)
        )
    ).all()
    return [{"id": row.id, "name": row.name, "code": row.code} for row in rows]


@router.get("/equipment")
async def assigned_equipment(
    project_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_equipment import field_equipment

    return await field_equipment(session, actor, project_id)


@router.get("/equipment/{asset_id}/history")
async def assigned_equipment_history(
    asset_id: uuid.UUID,
    project_id: uuid.UUID,
    kind: Literal["maintenance", "fuel", "meter"] = "maintenance",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_equipment import equipment_history

    return await equipment_history(session, actor, project_id, asset_id, kind, page, page_size)


@router.get("/shifts", response_model=list[DrillingShiftReportResponse])
async def field_shifts(
    project_id: uuid.UUID,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.services import drilling
    from app.services.field_equipment import require_project

    await require_project(session, actor, project_id)
    return await drilling.list_shift_reports(session, actor.organization_id, project_id=project_id)


@router.put("/shifts/{shift_id}", response_model=DrillingShiftReportResponse)
async def update_field_shift(
    shift_id: uuid.UUID,
    body: FieldShiftEdit,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_shifts import edit_shift

    return await edit_shift(session, actor, shift_id, body)


@router.get("/consumables/options")
async def field_consumable_options(
    project_id: uuid.UUID,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_consumables import consumption_options
    return await consumption_options(session, actor, project_id)


@router.get("/consumables")
async def list_field_consumables(
    project_id: uuid.UUID,
    log_date: date,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_consumables import field_consumptions
    return await field_consumptions(session, actor, project_id, log_date)


@router.post("/consumables", status_code=201)
async def create_field_consumables(
    body: ConsumptionCreate,
    actor: User = Depends(require_supervisor),
    session: AsyncSession = Depends(get_session),
):
    from app.services.field_consumables import log_consumption
    return await log_consumption(session, actor, body)

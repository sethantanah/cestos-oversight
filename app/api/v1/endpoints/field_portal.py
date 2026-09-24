"""Field portal reads with explicit role and team boundaries."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.core.dependencies import get_current_active_user, request_storage, scoped_roles
from app.core.exceptions import ForbiddenError
from app.db.session import get_session
from app.models import Employee, EmployeeAssignment, User, Project, Location, Asset
from app.models.operational_logs import FuelDelivery, FuelAllocation
from app.models.employee import AssignmentStatus, LeaveRequest
from app.schemas.drilling import DrillingShiftReportResponse
from app.schemas.operational_logs import FuelLogCreate, FuelReductionCreate, MaintenanceCreate, FuelDeliveryCreate, FuelAllocationCreate, FuelDeliveryUpdate, FuelAllocationUpdate
from app.services.employee_access import supervised_employee_ids
from app.services.field_consumables import ConsumptionCreate
from app.services.field_shifts import FieldShiftEdit
from app.services.field_work import FieldWorkEdit, FieldWorkUpdate

router = APIRouter(prefix="/field-portal", tags=["Field portal"])


@router.post("/fuel-deliveries", status_code=201)
async def create_fuel_delivery(body: FuelDeliveryCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    project = await session.scalar(select(Project).where(Project.id == body.project_id, Project.organization_id == actor.organization_id))
    site = await session.scalar(select(Location).where(Location.id == body.site_location_id, Location.project_id == body.project_id, Location.organization_id == actor.organization_id, Location.is_active.is_(True), Location.archived_at.is_(None)))
    if not project or not site:
        raise ForbiddenError("Select an active site belonging to the selected project")
    row = FuelDelivery(organization_id=actor.organization_id, created_by_id=actor.id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/fuel-deliveries")
async def list_fuel_deliveries(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    return list((await session.scalars(select(FuelDelivery).where(
        FuelDelivery.organization_id == actor.organization_id,
        FuelDelivery.archived_at.is_(None),
    ).order_by(FuelDelivery.recorded_at.desc()))).all())


@router.patch("/fuel-deliveries/{delivery_id}")
async def update_fuel_delivery(
    delivery_id: uuid.UUID,
    body: FuelDeliveryUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    delivery = await session.scalar(
        select(FuelDelivery).where(
            FuelDelivery.id == delivery_id,
            FuelDelivery.organization_id == actor.organization_id,
            FuelDelivery.archived_at.is_(None),
        )
    )
    if not delivery:
        raise ForbiddenError("Fuel delivery record not found")

    log_time = delivery.recorded_at or delivery.created_at
    if log_time:
        now_utc = datetime.now(timezone.utc)
        if log_time.tzinfo is None:
            log_time = log_time.replace(tzinfo=timezone.utc)
        if (now_utc - log_time) > timedelta(days=2):
            raise ForbiddenError("Fuel delivery records older than 2 days cannot be edited.")

    update_data = body.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(delivery, key, val)

    session.add(delivery)
    await session.commit()
    await session.refresh(delivery)
    return delivery


@router.post("/fuel-deliveries/{delivery_id}/receipt")
async def upload_fuel_delivery_receipt(
    delivery_id: uuid.UUID,
    receipt: UploadFile = File(...),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    delivery = await session.scalar(select(FuelDelivery).where(
        FuelDelivery.id == delivery_id,
        FuelDelivery.organization_id == actor.organization_id,
        FuelDelivery.archived_at.is_(None),
    ).with_for_update())
    if not delivery:
        raise HTTPException(404, "Fuel delivery record not found")
    data = await receipt.read(storage.max_bytes + 1)
    if not data:
        raise HTTPException(422, "Attach a non-empty receipt or delivery docket")
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"documents/{actor.organization_id}/fuel-deliveries",
            data,
            receipt.filename or "fuel-delivery-receipt.pdf",
            receipt.content_type,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    old_path = delivery.receipt_path
    delivery.receipt_path = stored.relative_path
    delivery.receipt_file_name = stored.filename
    delivery.receipt_mime_type = stored.mime_type
    delivery.receipt_size_bytes = stored.size_bytes
    delivery.updated_by_id = actor.id
    await session.commit()
    await session.refresh(delivery)
    if old_path and old_path != stored.relative_path:
        await run_in_threadpool(storage.delete, old_path)
    return {
        "delivery_id": str(delivery.id),
        "receipt_file_name": delivery.receipt_file_name,
        "receipt_mime_type": delivery.receipt_mime_type,
        "receipt_size_bytes": delivery.receipt_size_bytes,
    }


@router.get("/fuel-deliveries/{delivery_id}/receipt")
async def download_fuel_delivery_receipt(
    delivery_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
    storage=Depends(request_storage),
):
    delivery = await session.scalar(select(FuelDelivery).where(
        FuelDelivery.id == delivery_id,
        FuelDelivery.organization_id == actor.organization_id,
        FuelDelivery.archived_at.is_(None),
    ))
    if not delivery:
        raise HTTPException(404, "Fuel delivery record not found")
    if not delivery.receipt_path or not delivery.receipt_file_name:
        raise HTTPException(404, "No uploaded receipt is available for this fuel delivery")
    local = await run_in_threadpool(storage.resolve, delivery.receipt_path)
    return FileResponse(local, filename=delivery.receipt_file_name, media_type=delivery.receipt_mime_type)


@router.post("/fuel-allocations", status_code=201)
async def create_fuel_allocation(body: FuelAllocationCreate, actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    project = await session.scalar(select(Project).where(Project.id == body.project_id, Project.organization_id == actor.organization_id))
    site = await session.scalar(select(Location).where(Location.id == body.site_location_id, Location.project_id == body.project_id, Location.organization_id == actor.organization_id, Location.is_active.is_(True), Location.archived_at.is_(None)))
    asset = await session.scalar(select(Asset).where(Asset.id == body.asset_id, Asset.organization_id == actor.organization_id))
    if not project or not site or not asset:
        raise ForbiddenError("Select a valid project site and vehicle")
    if body.delivery_id:
        delivery = await session.scalar(select(FuelDelivery).where(
            FuelDelivery.id == body.delivery_id,
            FuelDelivery.organization_id == actor.organization_id,
            FuelDelivery.project_id == body.project_id,
            FuelDelivery.site_location_id == body.site_location_id,
            FuelDelivery.archived_at.is_(None),
        ))
        if not delivery:
            raise ForbiddenError("Select a fuel delivery from the same project site")
    row = FuelAllocation(organization_id=actor.organization_id, created_by_id=actor.id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "site_location_id": row.site_location_id,
        "asset_id": row.asset_id,
        "delivery_id": row.delivery_id,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else (row.created_at.isoformat() if row.created_at else None),
        "allocated_at": row.recorded_at.isoformat() if row.recorded_at else (row.created_at.isoformat() if row.created_at else None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "quantity_litres": row.quantity_litres,
        "notes": row.notes,
        "asset_name": asset.name or asset.asset_number or "Asset",
        "asset_number": asset.asset_number or "",
        "asset": {
            "id": asset.id,
            "name": asset.name or asset.asset_number or "Asset",
            "asset_number": asset.asset_number or "",
        },
    }


@router.get("/fuel-allocations")
async def list_fuel_allocations(actor: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    stmt = (
        select(FuelAllocation, Asset.name.label("ast_name"), Asset.asset_number.label("ast_number"))
        .outerjoin(Asset, FuelAllocation.asset_id == Asset.id)
        .where(
            FuelAllocation.organization_id == actor.organization_id,
            FuelAllocation.archived_at.is_(None),
        )
        .order_by(FuelAllocation.recorded_at.desc())
    )
    result = await session.execute(stmt)
    output = []
    for alloc, ast_name, ast_number in result.all():
        d = {
            "id": alloc.id,
            "organization_id": alloc.organization_id,
            "project_id": alloc.project_id,
            "site_location_id": alloc.site_location_id,
            "asset_id": alloc.asset_id,
            "delivery_id": alloc.delivery_id,
            "recorded_at": alloc.recorded_at.isoformat() if alloc.recorded_at else (alloc.created_at.isoformat() if alloc.created_at else None),
            "allocated_at": alloc.recorded_at.isoformat() if alloc.recorded_at else (alloc.created_at.isoformat() if alloc.created_at else None),
            "created_at": alloc.created_at.isoformat() if alloc.created_at else None,
            "quantity_litres": alloc.quantity_litres,
            "notes": alloc.notes,
            "asset_name": ast_name or ast_number or "Asset",
            "asset_number": ast_number or "",
            "asset": {
                "id": alloc.asset_id,
                "name": ast_name or ast_number or "Asset",
                "asset_number": ast_number or "",
            } if alloc.asset_id else None,
        }
        output.append(d)
    return output


@router.patch("/fuel-allocations/{allocation_id}")
async def update_fuel_allocation(
    allocation_id: uuid.UUID,
    body: FuelAllocationUpdate,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    allocation = await session.scalar(
        select(FuelAllocation).where(
            FuelAllocation.id == allocation_id,
            FuelAllocation.organization_id == actor.organization_id,
            FuelAllocation.archived_at.is_(None),
        )
    )
    if not allocation:
        raise ForbiddenError("Fuel allocation record not found")

    log_time = allocation.recorded_at or allocation.created_at
    if log_time:
        now_utc = datetime.now(timezone.utc)
        if log_time.tzinfo is None:
            log_time = log_time.replace(tzinfo=timezone.utc)
        if (now_utc - log_time) > timedelta(days=1):
            raise ForbiddenError("Fuel allocation records older than 1 day cannot be edited.")

    update_data = body.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(allocation, key, val)

    session.add(allocation)
    await session.commit()
    await session.refresh(allocation)

    asset = None
    if allocation.asset_id:
        asset = await session.scalar(select(Asset).where(Asset.id == allocation.asset_id, Asset.organization_id == actor.organization_id))

    ast_name = asset.name if asset else "Asset"
    ast_number = asset.asset_number if asset else ""

    return {
        "id": allocation.id,
        "organization_id": allocation.organization_id,
        "project_id": allocation.project_id,
        "site_location_id": allocation.site_location_id,
        "asset_id": allocation.asset_id,
        "delivery_id": allocation.delivery_id,
        "recorded_at": allocation.recorded_at.isoformat() if allocation.recorded_at else (allocation.created_at.isoformat() if allocation.created_at else None),
        "allocated_at": allocation.recorded_at.isoformat() if allocation.recorded_at else (allocation.created_at.isoformat() if allocation.created_at else None),
        "created_at": allocation.created_at.isoformat() if allocation.created_at else None,
        "quantity_litres": allocation.quantity_litres,
        "notes": allocation.notes,
        "asset_name": ast_name or ast_number or "Asset",
        "asset_number": ast_number or "",
        "asset": {
            "id": allocation.asset_id,
            "name": ast_name or ast_number or "Asset",
            "asset_number": ast_number or "",
        } if allocation.asset_id else None,
    }


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


@router.get("/sites")
async def field_project_sites(
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.models import Project
    from app.models.location import Location
    from app.services.field_equipment import assigned_project_ids
    rows = await session.execute(select(Location.id, Location.name, Location.project_id,
        Project.name.label("project_name")).join(Project, Project.id == Location.project_id).where(
        Location.organization_id == actor.organization_id, Location.is_active.is_(True),
        Location.archived_at.is_(None), Location.location_type != "HEAD_OFFICE",
        Project.organization_id == actor.organization_id,
        Project.id.in_(assigned_project_ids(actor))).order_by(Location.name))
    return [dict(row) for row in rows.mappings()]


@router.post("/employees/{employee_id}/contracts", status_code=201)
async def upload_field_employee_contract(
    employee_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    start_date: date | None = Form(None),
    end_date: date | None = Form(None),
    notes: str | None = Form(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    from app.core.config import request_storage
    from app.models import Employee
    from app.schemas.document import DocumentType
    from app.services.documents import DocumentService

    employee = await session.scalar(
        select(Employee).where(
            Employee.id == employee_id,
            Employee.organization_id == actor.organization_id,
        )
    )
    if not employee:
        raise ForbiddenError("Employee profile not found in your organization")

    if start_date:
        employee.contract_start_date = start_date
    if end_date:
        employee.contract_end_date = end_date
    session.add(employee)

    data = await file.read()
    doc_title = title or f"Employment Contract - {employee.first_name or ''} {employee.last_name or ''}".strip() or file.filename
    storage = request_storage(request)
    doc = await DocumentService(session, actor).upload(
        employee_id,
        data,
        file.filename,
        file.content_type,
        storage,
        DocumentType.EMPLOYMENT_CONTRACT,
        doc_title,
        None,
        start_date,
        end_date,
        None,
        notes,
        request,
    )
    await session.commit()
    return {"message": "Employment contract uploaded successfully", "employee_id": str(employee_id), "document_id": str(doc.id)}


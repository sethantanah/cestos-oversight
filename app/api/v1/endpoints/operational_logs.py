"""Scoped asset logs and project attachments, using the shared storage backend."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import require_permission
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.session import get_session
from app.models import AssetAssignment, Project, User
from app.models.asset_records import AssetInspection
from app.models.operational_logs import (
    AssetFuelLog,
    AssetFuelReduction,
    AssetLogFile,
    AssetMaintenanceJob,
    FuelSupplier,
    ProjectRecord,
)
from app.schemas.operational_logs import (
    FuelLogCreate,
    FuelLogUpdate,
    FuelReductionCreate,
    InspectionUpdate,
    MaintenanceCreate,
    MaintenanceStatus,
    MaintenanceUpdate,
    ProjectNoteCreate,
    RetireAsset,
)
from app.services.audit import record_audit
from app.services.equipment import EquipmentService

router = APIRouter(tags=["operating logs"])


def public(service: EquipmentService, row: Any) -> dict[str, Any]:
    data = service.public(row)
    if not service.permitted("assets.financial.read"):
        for key in ("unit_cost", "cost", "currency"):
            data.pop(key, None)
    return data


async def page_records(
    service: EquipmentService,
    model: Any,
    parent: str,
    identifier: uuid.UUID,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    query = select(model).where(
        model.organization_id == service.actor.organization_id, getattr(model, parent) == identifier
    )
    total = await service.session.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = (
        await service.session.scalars(
            query.order_by(model.created_at.desc(), model.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [public(service, row) for row in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def writable_asset(service: EquipmentService, asset_id: uuid.UUID) -> None:
    asset = await service.asset(asset_id, True)
    if not asset.is_active or asset.status.value in {"DISPOSED"}:
        raise ConflictError("This asset is retired or archived")


async def ensure_supplier_saved(
    session: AsyncSession,
    organization_id: uuid.UUID,
    supplier_name: str | None,
    actor_id: uuid.UUID,
) -> None:
    if not supplier_name or not supplier_name.strip():
        return
    clean_name = supplier_name.strip()
    existing = await session.scalar(
        select(FuelSupplier).where(
            FuelSupplier.organization_id == organization_id,
            func.lower(FuelSupplier.name) == clean_name.lower(),
        )
    )
    if not existing:
        new_sup = FuelSupplier(
            organization_id=organization_id,
            name=clean_name,
            created_by_id=actor_id,
        )
        session.add(new_sup)


@router.get("/fuel-suppliers")
async def get_fuel_suppliers(
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    rows = (
        await session.scalars(
            select(FuelSupplier)
            .where(FuelSupplier.organization_id == actor.organization_id)
            .order_by(FuelSupplier.name)
        )
    ).all()
    return [{"id": str(r.id), "name": r.name} for r in rows]


@router.get("/assets/{asset_id}/fuel-logs")
async def fuel_logs(
    asset_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    return await page_records(service, AssetFuelLog, "asset_id", asset_id, page, page_size)


@router.post("/assets/{asset_id}/fuel-logs", status_code=201)
async def create_fuel_log(
    asset_id: uuid.UUID,
    body: FuelLogCreate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    await service.ref(Project, body.project_id)
    row = AssetFuelLog(
        organization_id=actor.organization_id,
        asset_id=asset_id,
        created_by_id=actor.id,
        **body.model_dump(),
    )
    session.add(row)
    if body.supplier:
        await ensure_supplier_saved(session, actor.organization_id, body.supplier, actor.id)
    await session.flush()
    service.audit("asset.fuel_logged", asset_id, row)
    await service.commit()
    return public(service, row)


@router.patch("/assets/{asset_id}/fuel-logs/{log_id}")
async def update_fuel_log(
    asset_id: uuid.UUID,
    log_id: uuid.UUID,
    body: FuelLogUpdate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    row = await service.ref(AssetFuelLog, log_id, asset_id, lock=True)
    if body.project_id is not None:
        await service.ref(Project, body.project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by_id = actor.id
    if body.supplier:
        await ensure_supplier_saved(session, actor.organization_id, body.supplier, actor.id)
    service.audit("asset.fuel_log_updated", asset_id, row)
    await service.commit()
    return public(service, row)


@router.get("/assets/{asset_id}/fuel-reductions")
async def list_fuel_reductions(
    asset_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    return await page_records(service, AssetFuelReduction, "asset_id", asset_id, page, page_size)


@router.post("/assets/{asset_id}/fuel-reductions", status_code=201)
async def create_fuel_reduction(
    asset_id: uuid.UUID,
    body: FuelReductionCreate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    if body.fuel_log_id:
        await service.ref(AssetFuelLog, body.fuel_log_id, asset_id)
    row = AssetFuelReduction(
        organization_id=actor.organization_id,
        asset_id=asset_id,
        created_by_id=actor.id,
        **body.model_dump(),
    )
    session.add(row)
    await session.flush()
    service.audit("asset.fuel_reduction_recorded", asset_id, row)
    await service.commit()
    return public(service, row)


@router.get("/assets/{asset_id}/maintenance")
async def maintenance(
    asset_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    return await page_records(service, AssetMaintenanceJob, "asset_id", asset_id, page, page_size)


@router.post("/assets/{asset_id}/maintenance", status_code=201)
async def create_maintenance(
    asset_id: uuid.UUID,
    body: MaintenanceCreate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    await service.ref(Project, body.project_id)
    row = AssetMaintenanceJob(
        organization_id=actor.organization_id,
        asset_id=asset_id,
        created_by_id=actor.id,
        status="OPEN",
        **body.model_dump(),
    )
    session.add(row)
    await session.flush()
    service.audit("asset.maintenance_created", asset_id, row)
    await service.commit()
    return public(service, row)


@router.patch("/assets/{asset_id}/maintenance/{job_id}")
async def update_maintenance(
    asset_id: uuid.UUID,
    job_id: uuid.UUID,
    body: MaintenanceUpdate,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    row = await service.ref(AssetMaintenanceJob, job_id, asset_id, lock=True)
    if body.project_id is not None:
        await service.ref(Project, body.project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by_id = actor.id
    if body.status == "IN_PROGRESS" and not row.started_at:
        row.started_at = datetime.now(UTC)
    if body.status == "COMPLETED" and not row.completed_at:
        row.completed_at = datetime.now(UTC)
    service.audit("asset.maintenance_updated", asset_id, row)
    await service.commit()
    return public(service, row)


@router.post("/assets/{asset_id}/maintenance/{job_id}/status")
async def maintenance_status(
    asset_id: uuid.UUID,
    job_id: uuid.UUID,
    body: MaintenanceStatus,
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id, True)
    row = await service.ref(AssetMaintenanceJob, job_id, asset_id, lock=True)
    if row.status == body.status:
        return public(service, row)
    allowed = {
        "OPEN": {"IN_PROGRESS", "COMPLETED", "CANCELLED"},
        "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    }
    if body.status not in allowed.get(row.status, set()):
        raise ConflictError("Maintenance cannot move to this status")
    previous = row.status
    row.status = body.status
    row.updated_by_id = actor.id
    row.completion_notes = body.notes
    if body.status == "IN_PROGRESS" and not row.started_at:
        row.started_at = datetime.now(UTC)
    if body.status == "COMPLETED":
        row.completed_at = datetime.now(UTC)
    service.audit(
        "asset.maintenance_status_changed",
        asset_id,
        row,
        {"previous_status": previous, "status": body.status, "notes": body.notes},
    )
    await service.commit()
    return public(service, row)


@router.get("/assets/{asset_id}/logs/{log_type}/{log_id}/files")
async def list_log_files(
    asset_id: uuid.UUID,
    log_type: str,
    log_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    files = (
        await session.scalars(
            select(AssetLogFile).where(
                AssetLogFile.organization_id == actor.organization_id,
                AssetLogFile.asset_id == asset_id,
                AssetLogFile.log_type == log_type.upper(),
                AssetLogFile.log_id == log_id,
            )
        )
    ).all()
    return [service.public(f) for f in files]


@router.post("/assets/{asset_id}/logs/{log_type}/{log_id}/files", status_code=201)
async def upload_log_file(
    asset_id: uuid.UUID,
    log_type: str,
    log_id: uuid.UUID,
    request: Request,
    title: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    actor: User = Depends(require_permission("assets.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    storage = request.app.state.storage
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("File is empty")
    stored = await run_in_threadpool(
        storage.save,
        f"asset-log-files/{actor.organization_id}/{asset_id}/{log_type.lower()}",
        data,
        file.filename or "",
        file.content_type,
    )
    row = AssetLogFile(
        organization_id=actor.organization_id,
        asset_id=asset_id,
        log_type=log_type.upper(),
        log_id=log_id,
        title=title.strip(),
        storage_path=stored.relative_path,
        file_name=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        created_by_id=actor.id,
    )
    session.add(row)
    await session.flush()
    service.audit("asset.log_file_uploaded", asset_id, row)
    await service.commit()
    return service.public(row)


@router.get("/assets/{asset_id}/log-files/{file_id}/download")
async def download_log_file(
    asset_id: uuid.UUID,
    file_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    row = await service.ref(AssetLogFile, file_id)
    if not row or row.asset_id != asset_id:
        raise NotFoundError("File not found")
    path = await run_in_threadpool(request.app.state.storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("File not found")
    return FileResponse(path, filename=row.file_name, media_type="application/octet-stream")


@router.get("/assets/{asset_id}/operating-metrics")
async def operating_metrics(
    asset_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    filters = (
        AssetFuelLog.organization_id == actor.organization_id,
        AssetFuelLog.asset_id == asset_id,
    )
    quantity = await session.scalar(
        select(func.coalesce(func.sum(AssetFuelLog.quantity_litres), 0)).where(*filters)
    )
    month = func.date_trunc("month", AssetFuelLog.recorded_at)
    fuel = (
        (
            await session.execute(
                select(month.label("month"), func.sum(AssetFuelLog.quantity_litres).label("litres"))
                .where(*filters)
                .group_by(month)
                .order_by(month.desc())
                .limit(12)
            )
        )
        .mappings()
        .all()
    )
    jobs = (
        (
            await session.execute(
                select(AssetMaintenanceJob.status, func.count().label("count"))
                .where(
                    AssetMaintenanceJob.organization_id == actor.organization_id,
                    AssetMaintenanceJob.asset_id == asset_id,
                )
                .group_by(AssetMaintenanceJob.status)
            )
        )
        .mappings()
        .all()
    )
    result = {
        "fuel_litres": quantity or Decimal(0),
        "fuel_by_month": [dict(r) for r in reversed(fuel)],
        "maintenance_by_status": [dict(r) for r in jobs],
    }
    return result


@router.get("/projects/{project_id}/records")
async def project_records(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.ref(Project, project_id)
    return await page_records(service, ProjectRecord, "project_id", project_id, page, page_size)


def project_audit(session: AsyncSession, actor: User, row: ProjectRecord) -> None:
    record_audit(
        session,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="project.record_created",
        entity_type="project_record",
        entity_id=row.id,
        new_values={
            "project_id": str(row.project_id),
            "record_type": row.record_type,
            "title": row.title,
        },
    )


@router.post("/projects/{project_id}/records", status_code=201)
async def create_project_note(
    project_id: uuid.UUID,
    body: ProjectNoteCreate,
    actor: User = Depends(require_permission("projects.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.ref(Project, project_id)
    row = ProjectRecord(
        organization_id=actor.organization_id,
        project_id=project_id,
        created_by_id=actor.id,
        **body.model_dump(),
    )
    session.add(row)
    await session.flush()
    project_audit(session, actor, row)
    await service.commit()
    return service.public(row)


@router.post("/projects/{project_id}/files", status_code=201)
async def upload_project_file(
    project_id: uuid.UUID,
    request: Request,
    title: str = Form(..., min_length=1, max_length=200),
    description: str | None = Form(None, max_length=20000),
    file: UploadFile = File(...),
    actor: User = Depends(require_permission("projects.update")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.ref(Project, project_id)
    if not title.strip():
        raise ValidationError("File title is required")
    storage = request.app.state.storage
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("File is empty")
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"project-files/{actor.organization_id}/{project_id}",
            data,
            file.filename or "",
            file.content_type,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    try:
        row = ProjectRecord(
            organization_id=actor.organization_id,
            project_id=project_id,
            created_by_id=actor.id,
            record_type="FILE",
            title=title.strip(),
            description=description,
            storage_path=stored.relative_path,
            file_name=stored.filename,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
        )
        session.add(row)
        await session.flush()
        project_audit(session, actor, row)
        await service.commit()
        return service.public(row)
    except BaseException:
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise


@router.get("/projects/{project_id}/files/{record_id}/download")
async def download_project_file(
    project_id: uuid.UUID,
    record_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.ref(Project, project_id)
    row = await service.ref(ProjectRecord, record_id)
    if row.project_id != project_id or row.record_type != "FILE" or not row.storage_path:
        raise NotFoundError("File not found")
    expected = f"project-files/{actor.organization_id}/{project_id}/"
    if not row.storage_path.startswith(expected):
        raise NotFoundError("File not found")
    path = await run_in_threadpool(request.app.state.storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("File not found")
    return FileResponse(path, filename=row.file_name, media_type="application/octet-stream")


@router.post("/assets/{asset_id}/retire")
async def retire_asset(
    asset_id: uuid.UUID,
    body: RetireAsset,
    actor: User = Depends(require_permission("assets.archive")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from app.models.asset import AssetStatus

    service = EquipmentService(session, actor)
    service.require("assets.status.change")
    asset = await service.asset(asset_id, True)
    if not asset.is_active:
        return service.public(asset)
    if await service.active_assignment(asset_id):
        raise ConflictError("Complete the active project assignment before retiring this asset")
    active_jobs = await session.scalar(
        select(AssetMaintenanceJob.id)
        .where(
            AssetMaintenanceJob.organization_id == actor.organization_id,
            AssetMaintenanceJob.asset_id == asset_id,
            AssetMaintenanceJob.status.in_(["OPEN", "IN_PROGRESS"]),
        )
        .limit(1)
    )
    if active_jobs:
        raise ConflictError("Complete or cancel open maintenance before retiring this asset")
    if asset.status != AssetStatus.DISPOSED:
        service.status_event(asset, asset.status, AssetStatus.OUT_OF_SERVICE, body.reason)
    asset.is_active = False
    asset.archived_at = datetime.now(UTC)
    service.audit("asset.retired", asset_id, values={"reason": body.reason})
    await service.commit()
    return service.public(asset)


@router.patch("/assets/{asset_id}/inspections/{inspection_id}")
async def update_inspection(
    asset_id: uuid.UUID,
    inspection_id: uuid.UUID,
    body: InspectionUpdate,
    actor: User = Depends(require_permission("assets.inspections.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await writable_asset(service, asset_id)
    row = await service.ref(AssetInspection, inspection_id, asset_id, lock=True)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by_id = actor.id
    service.audit("asset.inspection_updated", asset_id, row)
    await service.commit()
    return service.public(row)


@router.get("/assets/{asset_id}/assignments/{assignment_id}/summary")
async def assignment_summary(
    asset_id: uuid.UUID,
    assignment_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    assignment = await service.ref(AssetAssignment, assignment_id, asset_id)
    if not assignment:
        raise NotFoundError("Assignment not found")
    start = assignment.assigned_at
    end = assignment.returned_at or datetime.now(UTC)

    fuel_query = select(
        func.coalesce(func.sum(AssetFuelLog.quantity_litres), 0).label("litres"),
        func.coalesce(func.sum(AssetFuelLog.quantity_litres * AssetFuelLog.unit_cost), 0).label(
            "cost"
        ),
    ).where(
        AssetFuelLog.organization_id == actor.organization_id,
        AssetFuelLog.asset_id == asset_id,
        AssetFuelLog.recorded_at >= start,
        AssetFuelLog.recorded_at <= end,
    )
    fuel_res = (await session.execute(fuel_query)).one()

    maint_query = select(
        func.coalesce(func.sum(AssetMaintenanceJob.cost), 0).label("cost"),
        func.count(AssetMaintenanceJob.id).label("count"),
    ).where(
        AssetMaintenanceJob.organization_id == actor.organization_id,
        AssetMaintenanceJob.asset_id == asset_id,
        AssetMaintenanceJob.created_at >= start,
        AssetMaintenanceJob.created_at <= end,
    )
    maint_res = (await session.execute(maint_query)).one()

    inspect_count = (
        await session.scalar(
            select(func.count(AssetInspection.id)).where(
                AssetInspection.organization_id == actor.organization_id,
                AssetInspection.asset_id == asset_id,
                AssetInspection.inspection_date >= start,
                AssetInspection.inspection_date <= end,
            )
        )
        or 0
    )

    return {
        "assignment_id": str(assignment.id),
        "project_id": str(assignment.project_id) if assignment.project_id else None,
        "assigned_at": assignment.assigned_at,
        "returned_at": assignment.returned_at,
        "start_meter": assignment.start_meter_reading,
        "end_meter": assignment.end_meter_reading,
        "fuel_litres": fuel_res.litres,
        "fuel_cost": fuel_res.cost if service.permitted("assets.financial.read") else None,
        "maintenance_cost": maint_res.cost if service.permitted("assets.financial.read") else None,
        "maintenance_count": maint_res.count,
        "inspections_count": inspect_count,
    }

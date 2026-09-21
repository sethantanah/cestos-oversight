"""Persist and expose work completion notes and evidence in both portals."""

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_active_user, require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import get_session
from app.models import User
from app.models.operational_logs import AssetLogFile, AssetMaintenanceJob
from app.services.field_work import FieldWorkUpdate, _work_access, public_job, update_work

router = APIRouter(tags=["work completion"])


def log_type(job):
    return "MAINTENANCE" if isinstance(job, AssetMaintenanceJob) else "WORK_ORDER"


async def completion_record(session, job, *, field=False):
    files = (
        await session.scalars(
            select(AssetLogFile)
            .where(
                AssetLogFile.organization_id == job.organization_id,
                AssetLogFile.asset_id == job.asset_id,
                AssetLogFile.log_id == job.id,
                AssetLogFile.log_type == log_type(job),
            )
            .order_by(AssetLogFile.created_at, AssetLogFile.id)
        )
    ).all()
    return {
        **public_job(job),
        "files": [
            {
                "id": row.id,
                "file_name": row.file_name,
                "title": row.title,
                "size_bytes": row.size_bytes,
                "download_url": (
                    f"/api/v1/field-portal/work-orders/{job.id}/completion/files/{row.id}"
                    if field
                    else f"/api/v1/assets/{job.asset_id}/log-files/{row.id}/download"
                ),
            }
            for row in files
        ],
    }


@router.post("/field-portal/work-orders/{job_id}/complete")
async def complete_work_order(
    job_id: uuid.UUID,
    request: Request,
    notes: str = Form(..., min_length=1, max_length=5000),
    file: UploadFile | None = File(None),
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    storage = request.app.state.storage
    stored = None
    try:
        await update_work(
            session, actor, job_id, FieldWorkUpdate(status="COMPLETED", note=notes), commit=False
        )
        job, _, _ = await _work_access(session, actor, job_id)
        if file is not None:
            content = await file.read(storage.max_bytes + 1)
            if not content:
                raise ValidationError("Completion file is empty")
            try:
                stored = await run_in_threadpool(
                    storage.save,
                    f"asset-log-files/{actor.organization_id}/{job.asset_id}/{log_type(job).lower()}",
                    content,
                    file.filename or "",
                    file.content_type,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            session.add(
                AssetLogFile(
                    organization_id=actor.organization_id,
                    asset_id=job.asset_id,
                    log_type=log_type(job),
                    log_id=job.id,
                    title="Completion evidence",
                    storage_path=stored.relative_path,
                    file_name=stored.filename,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    created_by_id=actor.id,
                )
            )
        await session.flush()
        result = await completion_record(session, job, field=True)
        await session.commit()
        return result
    except BaseException:
        await session.rollback()
        if stored is not None:
            await run_in_threadpool(storage.delete, stored.relative_path)
        raise


@router.get("/field-portal/work-orders/{job_id}/completion")
async def field_completion(
    job_id: uuid.UUID,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    job, _, _ = await _work_access(session, actor, job_id)
    return await completion_record(session, job, field=True)


@router.get("/field-portal/work-orders/{job_id}/completion/files/{file_id}")
async def field_completion_file(
    job_id: uuid.UUID,
    file_id: uuid.UUID,
    request: Request,
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
):
    job, _, _ = await _work_access(session, actor, job_id)
    row = await session.scalar(
        select(AssetLogFile).where(
            AssetLogFile.id == file_id,
            AssetLogFile.organization_id == actor.organization_id,
            AssetLogFile.asset_id == job.asset_id,
            AssetLogFile.log_id == job.id,
            AssetLogFile.log_type == log_type(job),
        )
    )
    prefix = f"asset-log-files/{actor.organization_id}/{job.asset_id}/{log_type(job).lower()}/"
    if row is None or not row.storage_path.startswith(prefix):
        raise NotFoundError("Completion document not found")
    path = await run_in_threadpool(request.app.state.storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("Completion document not found")
    return FileResponse(path, filename=row.file_name, media_type="application/octet-stream")


@router.get("/assets/{asset_id}/logs/{kind}/{job_id}/completion")
async def asset_completion(
    asset_id: uuid.UUID,
    kind: str,
    job_id: uuid.UUID,
    actor: User = Depends(require_permission("assets.read")),
    session: AsyncSession = Depends(get_session),
):
    from app.models.maintenance_hse import MaintenanceWorkOrder
    from app.services.equipment import EquipmentService

    model = {"MAINTENANCE": AssetMaintenanceJob, "WORK_ORDER": MaintenanceWorkOrder}.get(
        kind.upper()
    )
    if model is None:
        raise NotFoundError("Work order not found")
    service = EquipmentService(session, actor)
    await service.asset(asset_id)
    job = await service.ref(model, job_id, asset_id)
    return await completion_record(session, job)

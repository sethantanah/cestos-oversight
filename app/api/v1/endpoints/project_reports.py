"""Project reporting, portfolio metrics and attributed activity."""

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import get_session
from app.models import AssetAssignment, AuditLog, EmployeeAssignment, Location, Project, User
from app.models.project_report import ProjectReport
from app.schemas.project_report import ProjectReportCreate, ProjectReportUpdate
from app.services.activity import present_activity
from app.services.audit import record_audit, request_metadata
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def public_report(row: ProjectReport) -> dict[str, Any]:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "storage_path"}


async def visible_reports(session, actor, rows):
    from app.models.document_library import LibraryDocument
    from app.services.document_access import visible_scope

    paths = set(
        (
            await session.scalars(
                select(LibraryDocument.storage_path).where(
                    visible_scope(actor), LibraryDocument.source_type == "project_reports"
                )
            )
        ).all()
    )
    result = []
    for row in rows:
        payload = public_report(row)
        if row.storage_path and row.storage_path not in paths:
            for key in ("file_name", "mime_type", "size_bytes"):
                payload[key] = None
        result.append(payload)
    return result


async def report_metrics(
    session: AsyncSession, organization_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> dict[str, Any]:
    filters = [ProjectReport.organization_id == organization_id]
    if project_id is not None:
        filters.append(ProjectReport.project_id == project_id)
    values = (
        (
            await session.execute(
                select(
                    func.count(ProjectReport.id).label("reports"),
                    func.coalesce(func.sum(ProjectReport.metres), 0).label("metres"),
                    func.coalesce(func.sum(ProjectReport.drill_holes), 0).label("drill_holes"),
                    (
                        func.sum(ProjectReport.average_depth * ProjectReport.drill_holes)
                        / func.nullif(func.sum(ProjectReport.drill_holes), 0)
                    ).label("average_depth"),
                    func.max(ProjectReport.report_date).label("last_report_date"),
                ).where(*filters)
            )
        )
        .mappings()
        .one()
    )
    month = func.date_trunc("month", ProjectReport.report_date)
    trend = (
        (
            await session.execute(
                select(
                    month.label("month"),
                    func.sum(ProjectReport.metres).label("metres"),
                    func.sum(ProjectReport.drill_holes).label("drill_holes"),
                )
                .where(*filters, ProjectReport.report_type == "DRILLING_UPDATE")
                .group_by(month)
                .order_by(month.desc())
                .limit(12)
            )
        )
        .mappings()
        .all()
    )
    return {**dict(values), "by_month": [dict(r) for r in reversed(trend)]}


@router.get("/dashboard-summary")
async def dashboard(
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    org = actor.organization_id
    states = (
        await session.execute(
            select(Project.status, func.count())
            .where(Project.organization_id == org, Project.is_active.is_(True))
            .group_by(Project.status)
        )
    ).all()
    cutoff = datetime.now(UTC).date() - timedelta(days=7)
    active = ["ACTIVE", "MOBILIZING"]
    recent = select(ProjectReport.project_id).where(
        ProjectReport.organization_id == org, ProjectReport.report_date >= cutoff
    )
    overdue = await session.scalar(
        select(func.count(Project.id)).where(
            Project.organization_id == org,
            Project.is_active.is_(True),
            Project.status.in_(active),
            Project.expected_end_date < datetime.now(UTC).date(),
        )
    )
    stale = await session.scalar(
        select(func.count(Project.id)).where(
            Project.organization_id == org,
            Project.is_active.is_(True),
            Project.status.in_(active),
            Project.id.not_in(recent),
        )
    )
    return {
        "total": sum(n for _, n in states),
        "by_status": {status: count for status, count in states},
        "overdue": overdue,
        "without_recent_update": stale,
        **await report_metrics(session, org),
    }


@router.get("/{project_id}/report-metrics")
async def metrics(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = await ProjectService(session, actor)._get_or_404(project_id)
    result = await report_metrics(session, actor.organization_id, project_id)
    result["target_metres"] = project.target_metres
    result["target_progress"] = (
        result["metres"] / project.target_metres * 100 if project.target_metres else None
    )
    return result


@router.get("/{project_id}/reports")
async def reports(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    report_type: str | None = None,
    site_id: uuid.UUID | None = None,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ProjectService(session, actor)._get_or_404(project_id)
    query = select(ProjectReport).where(
        ProjectReport.organization_id == actor.organization_id,
        ProjectReport.project_id == project_id,
    )
    if report_type:
        query = query.where(ProjectReport.report_type == report_type)
    if site_id:
        query = query.where(ProjectReport.site_id == site_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = (
        await session.scalars(
            query.order_by(
                ProjectReport.report_date.desc(),
                ProjectReport.created_at.desc(),
                ProjectReport.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": await visible_reports(session, actor, items),
        "total": total,
        "page": page,
        "pages": math.ceil(total / page_size),
    }


@router.post("/{project_id}/reports", status_code=201)
async def create_report(
    project_id: uuid.UUID,
    request: Request,
    report: str = Form(...),
    file: UploadFile | None = File(None),
    actor: User = Depends(require_permission("projects.update")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        body = ProjectReportCreate.model_validate_json(report)
    except PydanticValidationError as error:
        raise ValidationError("; ".join(e["msg"] for e in error.errors())) from error
    await ProjectService(session, actor)._get_or_404(project_id)
    site = await session.scalar(
        select(Location).where(
            Location.id == body.site_id,
            Location.organization_id == actor.organization_id,
            Location.project_id == project_id,
            Location.is_active.is_(True),
            Location.location_type == "PROJECT_SITE",
        )
    )
    if site is None:
        raise ValidationError("Select an active project site belonging to this project")
    stored = None
    storage = request.app.state.storage
    try:
        if file is not None:
            data = await file.read(storage.max_bytes + 1)
            if not data:
                raise ValidationError("File is empty")
            try:
                stored = await run_in_threadpool(
                    storage.save,
                    f"project-reports/{actor.organization_id}/{project_id}",
                    data,
                    file.filename or "",
                    file.content_type,
                )
            except ValueError as error:
                raise ValidationError(str(error)) from error
        row = ProjectReport(
            **body.model_dump(),
            project_id=project_id,
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            author_name=" ".join(filter(None, [actor.first_name, actor.last_name]))
            or "Team member",
            site_name=site.name,
            storage_path=stored.relative_path if stored else None,
            file_name=stored.filename if stored else None,
            mime_type=stored.mime_type if stored else None,
            size_bytes=stored.size_bytes if stored else None,
        )
        session.add(row)
        await session.flush()
        record_audit(
            session,
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            action="project.report_created",
            entity_type="project",
            entity_id=project_id,
            new_values=jsonable_encoder(
                {
                    **body.model_dump(),
                    "report_id": row.id,
                    "project_id": project_id,
                    "site_name": row.site_name,
                    "author_name": row.author_name,
                    "file_name": row.file_name,
                    "size_bytes": row.size_bytes,
                }
            ),
            **request_metadata(request),
        )
        await session.commit()
        return (await visible_reports(session, actor, [row]))[0]
    except BaseException:
        await session.rollback()
        if stored:
            await run_in_threadpool(storage.delete, stored.relative_path)
        raise


@router.patch("/{project_id}/reports/{report_id}")
async def update_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    request: Request,
    report: str = Form(...),
    file: UploadFile | None = File(None),
    actor: User = Depends(require_permission("projects.update")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        body = ProjectReportUpdate.model_validate_json(report)
    except PydanticValidationError as error:
        raise ValidationError("; ".join(e["msg"] for e in error.errors())) from error

    await ProjectService(session, actor)._get_or_404(project_id)
    row = await session.scalar(
        select(ProjectReport).where(
            ProjectReport.organization_id == actor.organization_id,
            ProjectReport.project_id == project_id,
            ProjectReport.id == report_id,
        )
    )
    if row is None:
        raise NotFoundError("Report not found")

    if file is not None and row.storage_path:
        from app.services.document_access import require_document_path

        await require_document_path(session, actor, row.storage_path)
    old_values = public_report(row)
    updates = body.model_dump(exclude_unset=True)

    if "site_id" in updates and updates["site_id"] is not None:
        site = await session.scalar(
            select(Location).where(
                Location.id == updates["site_id"],
                Location.organization_id == actor.organization_id,
                Location.project_id == project_id,
                Location.is_active.is_(True),
                Location.location_type == "PROJECT_SITE",
            )
        )
        if site is None:
            raise ValidationError("Select an active project site belonging to this project")
        row.site_name = site.name

    for key, val in updates.items():
        if val is not None:
            setattr(row, key, val)

    stored = None
    storage = request.app.state.storage
    if file is not None:
        data = await file.read(storage.max_bytes + 1)
        if data:
            stored = await run_in_threadpool(
                storage.save,
                f"project-reports/{actor.organization_id}/{project_id}",
                data,
                file.filename or "",
                file.content_type,
            )
            row.storage_path = stored.relative_path
            row.file_name = stored.filename
            row.mime_type = stored.mime_type
            row.size_bytes = stored.size_bytes

    record_audit(
        session,
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        action="project.report_updated",
        entity_type="project",
        entity_id=project_id,
        old_values=old_values,
        new_values=public_report(row),
        **request_metadata(request),
    )
    await session.commit()
    return (await visible_reports(session, actor, [row]))[0]


@router.get("/{project_id}/reports/{report_id}/attachment")
async def attachment(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    request: Request,
    inline: bool = Query(False),
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await ProjectService(session, actor)._get_or_404(project_id)
    row = await session.scalar(
        select(ProjectReport).where(
            ProjectReport.organization_id == actor.organization_id,
            ProjectReport.project_id == project_id,
            ProjectReport.id == report_id,
        )
    )
    prefix = f"project-reports/{actor.organization_id}/{project_id}/"
    if row is None or not row.storage_path or not row.storage_path.startswith(prefix):
        raise NotFoundError("Attachment not found")
    from app.services.document_access import require_document_path

    await require_document_path(session, actor, row.storage_path)
    path = await run_in_threadpool(request.app.state.storage.resolve, row.storage_path)
    if not path.is_file():
        raise NotFoundError("Attachment not found")

    import mimetypes

    guessed_type, _ = mimetypes.guess_type(row.file_name or "")
    media_type = row.mime_type or guessed_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    filename = row.file_name or "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"'}
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/{project_id}/activity")
async def activity(
    project_id: uuid.UUID,
    page: int = Query(1, ge=1),
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ProjectService(session, actor)._get_or_404(project_id)
    assignment_ids = select(EmployeeAssignment.id).where(
        EmployeeAssignment.organization_id == actor.organization_id,
        EmployeeAssignment.project_id == project_id,
    )
    asset_assignment_ids = select(AssetAssignment.id).where(
        AssetAssignment.organization_id == actor.organization_id,
        AssetAssignment.project_id == project_id,
    )
    site_ids = select(Location.id).where(
        Location.organization_id == actor.organization_id, Location.project_id == project_id
    )
    filters = [
        AuditLog.organization_id == actor.organization_id,
        or_(
            and_(AuditLog.entity_type == "project", AuditLog.entity_id == project_id),
            AuditLog.new_values["project_id"].astext == str(project_id),
            AuditLog.old_values["project_id"].astext == str(project_id),
            and_(
                AuditLog.entity_type.in_(["asset_assignment", "asset_assignments"]),
                AuditLog.entity_id.in_(asset_assignment_ids),
            ),
            and_(
                AuditLog.entity_type.in_(["location", "locations"]),
                AuditLog.new_values["project_id"].astext.is_(None),
                AuditLog.old_values["project_id"].astext.is_(None),
                AuditLog.entity_id.in_(site_ids),
            ),
            and_(
                AuditLog.entity_type.in_(["employee_assignment", "employee_assignments"]),
                AuditLog.entity_id.in_(assignment_ids),
            ),
        ),
    ]
    total = await session.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0
    entries = (
        await session.execute(
            select(AuditLog, User.first_name, User.last_name)
            .outerjoin(
                User,
                and_(
                    User.id == AuditLog.actor_user_id, User.organization_id == actor.organization_id
                ),
            )
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return {
        "total": total,
        "items": await present_activity(session, actor.organization_id, entries),
    }

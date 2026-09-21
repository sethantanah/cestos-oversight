"""Project reporting, portfolio metrics and attributed activity."""

import math
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    from app.models.drilling import DrillHole, DrillingShiftInterval, DrillingShiftReport

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

    # Combine metrics with drilling shift production reports
    shift_filters = [
        DrillingShiftReport.organization_id == organization_id,
        DrillingShiftReport.status.in_(["APPROVED", "SUBMITTED"]),
        DrillingShiftReport.archived_at.is_(None),
    ]
    if project_id is not None:
        shift_filters.append(DrillingShiftReport.project_id == project_id)

    shift_metrics = (
        (
            await session.execute(
                select(
                    func.count(DrillingShiftReport.id).label("shift_count"),
                    func.coalesce(func.sum(DrillingShiftReport.total_metres), 0).label("shift_metres"),
                    func.max(DrillingShiftReport.date).label("last_shift_date"),
                ).where(*shift_filters)
            )
        )
        .mappings()
        .one()
    )

    # Count distinct worked drill holes from shift intervals
    shift_holes_count = await session.scalar(
        select(func.count(func.distinct(DrillingShiftInterval.drill_hole_id)))
        .select_from(DrillingShiftInterval)
        .join(DrillingShiftReport, DrillingShiftInterval.shift_report_id == DrillingShiftReport.id)
        .where(*shift_filters)
    ) or 0

    # Average depth reached across shift intervals
    shift_avg_depth = float((await session.scalar(
        select(func.coalesce(func.avg(DrillingShiftInterval.to_depth_m), 0))
        .select_from(DrillingShiftInterval)
        .join(DrillingShiftReport, DrillingShiftInterval.shift_report_id == DrillingShiftReport.id)
        .where(*shift_filters)
    )) or 0.0)

    # Count total drill holes in DrillHole table
    hole_filters = [
        DrillHole.organization_id == organization_id,
        DrillHole.archived_at.is_(None),
    ]
    if project_id is not None:
        hole_filters.append(DrillHole.project_id == project_id)

    project_holes_count = await session.scalar(
        select(func.count(DrillHole.id)).where(*hole_filters)
    ) or 0

    r_dict = dict(values)
    s_dict = dict(shift_metrics)

    field_metres = Decimal(str(r_dict.get("metres") or 0))
    shift_metres = Decimal(str(s_dict.get("shift_metres") or 0))

    total_metres = max(field_metres, shift_metres) if shift_metres > 0 else field_metres
    total_reports = int(r_dict.get("reports") or 0) + int(s_dict.get("shift_count") or 0)

    last_r_date = r_dict.get("last_report_date")
    last_s_date = s_dict.get("last_shift_date")
    latest_date = max([d for d in [last_r_date, last_s_date] if d is not None], default=None)

    field_holes = int(r_dict.get("drill_holes") or 0)
    total_holes = max(field_holes, shift_holes_count, project_holes_count)

    field_avg_depth = float(r_dict.get("average_depth") or 0.0)
    if field_avg_depth > 0 and shift_avg_depth > 0:
        combined_avg_depth = round((field_avg_depth + shift_avg_depth) / 2.0, 2)
    elif shift_avg_depth > 0:
        combined_avg_depth = round(shift_avg_depth, 2)
    else:
        combined_avg_depth = round(field_avg_depth, 2)

    r_dict["metres"] = float(total_metres)
    r_dict["reports"] = total_reports
    r_dict["drill_holes"] = total_holes
    r_dict["average_depth"] = combined_avg_depth
    if latest_date:
        r_dict["last_report_date"] = latest_date

    # Calculate monthly trends from ProjectReport
    field_month = func.date_trunc("month", ProjectReport.report_date)
    field_trend = (
        (
            await session.execute(
                select(
                    field_month.label("month"),
                    func.coalesce(func.sum(ProjectReport.metres), 0).label("metres"),
                    func.coalesce(func.sum(ProjectReport.drill_holes), 0).label("drill_holes"),
                )
                .where(*filters, ProjectReport.report_type == "DRILLING_UPDATE")
                .group_by(field_month)
            )
        )
        .mappings()
        .all()
    )

    # Calculate monthly trends from DrillingShiftReport
    shift_month = func.date_trunc("month", DrillingShiftReport.date)
    shift_trend = (
        (
            await session.execute(
                select(
                    shift_month.label("month"),
                    func.coalesce(func.sum(DrillingShiftReport.total_metres), 0).label("metres"),
                )
                .where(*shift_filters)
                .group_by(shift_month)
            )
        )
        .mappings()
        .all()
    )

    # Monthly distinct worked drill holes from intervals
    shift_interval_holes = (
        (
            await session.execute(
                select(
                    shift_month.label("month"),
                    func.count(func.distinct(DrillingShiftInterval.drill_hole_id)).label("drill_holes"),
                )
                .select_from(DrillingShiftInterval)
                .join(DrillingShiftReport, DrillingShiftInterval.shift_report_id == DrillingShiftReport.id)
                .where(*shift_filters)
                .group_by(shift_month)
            )
        )
        .mappings()
        .all()
    )

    def to_month_str(val: Any) -> str:
        if val is None:
            return ""
        return str(val)[:7]

    field_metres_by_month = {to_month_str(r["month"]): Decimal(str(r["metres"] or 0)) for r in field_trend if r["month"]}
    field_holes_by_month = {to_month_str(r["month"]): int(r["drill_holes"] or 0) for r in field_trend if r["month"]}

    shift_metres_by_month = {to_month_str(r["month"]): Decimal(str(r["metres"] or 0)) for r in shift_trend if r["month"]}
    shift_holes_by_month = {to_month_str(r["month"]): int(r["drill_holes"] or 0) for r in shift_interval_holes if r["month"]}

    all_month_keys = sorted(
        [k for k in set(field_metres_by_month.keys()) | set(shift_metres_by_month.keys()) if k],
        reverse=True,
    )[:12]

    by_month = []
    for m_key in reversed(all_month_keys):
        f_m = field_metres_by_month.get(m_key, Decimal("0"))
        s_m = shift_metres_by_month.get(m_key, Decimal("0"))
        m_metres = max(f_m, s_m) if s_m > 0 else f_m

        f_h = field_holes_by_month.get(m_key, 0)
        s_h = shift_holes_by_month.get(m_key, 0)
        m_holes = max(f_h, s_h) if s_h > 0 else f_h

        by_month.append({
            "month": f"{m_key}-01",
            "metres": float(m_metres),
            "drill_holes": m_holes,
        })

    return {**r_dict, "by_month": by_month}


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
    target_m = float(project.target_metres) if project.target_metres is not None else None
    metres = float(result.get("metres") or 0.0)
    result["target_metres"] = target_m
    result["target_progress"] = (
        round((metres / target_m) * 100.0, 2) if target_m and target_m > 0 else None
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
    from sqlalchemy.orm import selectinload
    from app.models.drilling import DrillingShiftReport
    from app.models.employee import Employee

    await ProjectService(session, actor)._get_or_404(project_id)
    query = select(ProjectReport).where(
        ProjectReport.organization_id == actor.organization_id,
        ProjectReport.project_id == project_id,
    )
    if report_type:
        query = query.where(ProjectReport.report_type == report_type)
    if site_id:
        query = query.where(ProjectReport.site_id == site_id)

    project_report_rows = (
        await session.scalars(
            query.order_by(
                ProjectReport.report_date.desc(),
                ProjectReport.created_at.desc(),
                ProjectReport.id.desc(),
            )
        )
    ).all()
    field_items = await visible_reports(session, actor, project_report_rows)

    shift_items = []
    if report_type in (None, "DRILLING_UPDATE"):
        shift_query = (
            select(DrillingShiftReport)
            .where(
                DrillingShiftReport.organization_id == actor.organization_id,
                DrillingShiftReport.project_id == project_id,
                DrillingShiftReport.archived_at.is_(None),
            )
            .options(selectinload(DrillingShiftReport.intervals))
        )
        shift_rows = (await session.scalars(shift_query)).all()

        sup_ids = {s.supervisor_id for s in shift_rows if s.supervisor_id}
        sup_map = {}
        if sup_ids:
            emp_rows = (await session.scalars(select(Employee).where(Employee.id.in_(sup_ids)))).all()
            sup_map = {e.id: f"{e.first_name} {e.last_name}".strip() for e in emp_rows}

        sub_ids = {s.submitted_by_id for s in shift_rows if s.submitted_by_id}
        user_map = {}
        if sub_ids:
            user_rows = (await session.scalars(select(User).where(User.id.in_(sub_ids)))).all()
            user_map = {u.id: u.full_name for u in user_rows}

        project_site = await session.scalar(
            select(Location).where(
                Location.organization_id == actor.organization_id,
                Location.location_type == "PROJECT_SITE",
                Location.is_active.is_(True),
            )
        )
        default_site_id = str(project_site.id) if project_site else None
        default_site_name = project_site.name if project_site else "Main Site"

        for s in shift_rows:
            if site_id and default_site_id and str(site_id) != str(default_site_id):
                continue

            intervals = s.intervals or []
            distinct_holes = len({i.drill_hole_id for i in intervals if i.drill_hole_id})
            max_depth = max([float(i.to_depth_m) for i in intervals if i.to_depth_m is not None], default=0.0)

            author = "System"
            if s.supervisor_id and s.supervisor_id in sup_map:
                author = f"{sup_map[s.supervisor_id]} (Supervisor)"
            elif s.submitted_by_id and s.submitted_by_id in user_map:
                author = user_map[s.submitted_by_id]

            shift_num = s.report_number or f"SR-{str(s.id)[:8].upper()}"
            core_str = f" | Core Recovery: {s.avg_core_recovery_pct}%" if s.avg_core_recovery_pct is not None else ""
            notes_full = f"[Daily Shift Log {shift_num}]{core_str}. {s.notes or ''}".strip()

            shift_items.append(
                {
                    "id": str(s.id),
                    "organization_id": str(s.organization_id),
                    "project_id": str(s.project_id),
                    "site_id": default_site_id,
                    "site_name": default_site_name,
                    "report_type": "DRILLING_UPDATE",
                    "report_date": str(s.date),
                    "title": f"Daily Shift Production Report {shift_num} ({s.shift_type} Shift)",
                    "notes": notes_full,
                    "metres": float(s.total_metres or 0.0),
                    "drill_holes": distinct_holes or (1 if s.total_metres > 0 else 0),
                    "average_depth": max_depth,
                    "author_name": author,
                    "storage_path": None,
                    "file_name": None,
                    "mime_type": None,
                    "size_bytes": None,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "is_shift_report": True,
                    "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                }
            )

    combined = field_items + shift_items

    def sort_key(item):
        r_date = str(item.get("report_date") or "")
        c_at = str(item.get("created_at") or "")
        return (r_date, c_at)

    combined.sort(key=sort_key, reverse=True)

    total = len(combined)
    paginated_items = combined[(page - 1) * page_size : page * page_size]

    return {
        "items": paginated_items,
        "total": total,
        "page": page,
        "pages": math.ceil(total / page_size) if total > 0 else 1,
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

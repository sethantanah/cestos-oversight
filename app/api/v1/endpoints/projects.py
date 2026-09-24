import uuid
from collections.abc import Sequence
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.db.session import get_session
from app.models import User
from app.models.project import ProjectStatus
from app.schemas.asset import AssetRead
from app.schemas.common import Page
from app.schemas.employee import EmployeeRead, ManpowerSummary
from app.schemas.location import LocationRead
from app.schemas.project import ProjectCreate, ProjectOverview, ProjectRead, ProjectUpdate
from app.services.employees import EmployeeService
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/field-admin-metrics")
async def field_admin_project_metrics(
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return project counts from current assignment records for the Field Admin cards."""
    from datetime import UTC, datetime
    from sqlalchemy import func, or_, select
    from app.models import Asset, AssetAssignment, EmployeeAssignment, Project
    from app.models.employee import AssignmentStatus
    from app.models.maintenance_hse import MaintenanceWorkOrder, WorkOrderStatus

    now = datetime.now(UTC)
    today = date.today()
    assigned_asset_ids = select(AssetAssignment.asset_id).join(
        Asset, Asset.id == AssetAssignment.asset_id
    ).where(
        AssetAssignment.organization_id == actor.organization_id,
        AssetAssignment.project_id == Project.id,
        AssetAssignment.status == "ACTIVE",
        AssetAssignment.assigned_at <= now,
        or_(AssetAssignment.returned_at.is_(None), AssetAssignment.returned_at > now),
        Asset.organization_id == actor.organization_id,
        Asset.is_active.is_(True),
        Asset.archived_at.is_(None),
    ).correlate(Project)
    asset_count = select(func.count(func.distinct(AssetAssignment.asset_id))).join(
        Asset, Asset.id == AssetAssignment.asset_id
    ).where(
        AssetAssignment.organization_id == actor.organization_id,
        AssetAssignment.project_id == Project.id,
        AssetAssignment.status == "ACTIVE",
        AssetAssignment.assigned_at <= now,
        or_(AssetAssignment.returned_at.is_(None), AssetAssignment.returned_at > now),
        Asset.organization_id == actor.organization_id,
        Asset.is_active.is_(True),
        Asset.archived_at.is_(None),
    ).correlate(Project).scalar_subquery()
    crew_count = select(func.count(func.distinct(EmployeeAssignment.employee_id))).where(
        EmployeeAssignment.organization_id == actor.organization_id,
        EmployeeAssignment.project_id == Project.id,
        EmployeeAssignment.status == AssignmentStatus.ACTIVE,
        EmployeeAssignment.start_date <= today,
        or_(EmployeeAssignment.end_date.is_(None), EmployeeAssignment.end_date >= today),
    ).correlate(Project).scalar_subquery()
    open_work_order_count = select(func.count(func.distinct(MaintenanceWorkOrder.id))).where(
        MaintenanceWorkOrder.organization_id == actor.organization_id,
        MaintenanceWorkOrder.is_active.is_(True),
        MaintenanceWorkOrder.archived_at.is_(None),
        MaintenanceWorkOrder.status.notin_([WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED]),
        or_(
            MaintenanceWorkOrder.project_id == Project.id,
            MaintenanceWorkOrder.asset_id.in_(assigned_asset_ids),
        ),
    ).correlate(Project).scalar_subquery()
    rows = await session.execute(select(
        Project.id.label("project_id"),
        asset_count.label("asset_count"),
        crew_count.label("crew_count"),
        open_work_order_count.label("open_work_order_count"),
    ).where(
        Project.organization_id == actor.organization_id,
        Project.archived_at.is_(None),
    ))
    return [dict(row) for row in rows.mappings()]


@router.get("", response_model=Page[ProjectRead])
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    client_id: uuid.UUID | None = None,
    status: ProjectStatus | None = None,
    project_manager_id: uuid.UUID | None = None,
    start_date_from: date | None = None,
    start_date_to: date | None = None,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectRead]:
    return await ProjectService(session, actor).list(
        page,
        page_size,
        search,
        client_id,
        status,
        project_manager_id,
        start_date_from,
        start_date_to,
    )


@router.get("/dashboard-summary")
async def projects_dashboard_summary(
    status: ProjectStatus | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    location_id: uuid.UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from sqlalchemy import func, select
    from app.models.project import Project, ProjectStatus
    from datetime import UTC, datetime

    stmt = select(Project).where(
        Project.organization_id == actor.organization_id,
        Project.archived_at.is_(None),
    )
    if status:
        stmt = stmt.where(Project.status == status)
    if client_id:
        stmt = stmt.where(Project.client_id == client_id)
    if location_id:
        stmt = stmt.where(Project.location_id == location_id)
    if date_from:
        stmt = stmt.where(Project.start_date >= date_from)
    if date_to:
        stmt = stmt.where(Project.start_date <= date_to)

    rows = (await session.scalars(stmt)).all()
    total = len(rows)

    by_status: dict[str, int] = {}
    overdue = 0
    today = date.today()

    for p in rows:
        st = str(p.status.value if hasattr(p.status, "value") else p.status)
        by_status[st] = by_status.get(st, 0) + 1
        if p.status == ProjectStatus.ACTIVE and p.end_date and p.end_date < today:
            overdue += 1

    return {
        "total": total,
        "by_status": by_status,
        "overdue": overdue,
        "without_recent_update": 0,
    }


@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(
    body: ProjectCreate,
    request: Request,
    actor: User = Depends(require_permission("projects.create")),
    session: AsyncSession = Depends(get_session),
) -> ProjectRead:
    return await ProjectService(session, actor).create(body, request)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> ProjectRead:
    return await ProjectService(session, actor).get(project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    request: Request,
    actor: User = Depends(require_permission("projects.update")),
    session: AsyncSession = Depends(get_session),
) -> ProjectRead:
    return await ProjectService(session, actor).update(project_id, body, request)


@router.get("/{project_id}/overview", response_model=ProjectOverview)
async def project_overview(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> ProjectOverview:
    return await ProjectService(session, actor).overview(project_id)


@router.get("/{project_id}/employees", response_model=list[EmployeeRead])
async def list_project_employees(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[EmployeeRead]:
    return await ProjectService(session, actor).project_employees(project_id)


@router.get("/{project_id}/assets", response_model=list[AssetRead])
async def list_project_assets(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[AssetRead]:
    return await ProjectService(session, actor).project_assets(project_id)


@router.get("/{project_id}/sites", response_model=list[LocationRead])
async def list_project_sites(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> Sequence[LocationRead]:
    return await ProjectService(session, actor).project_sites(project_id)


@router.get("/{project_id}/manpower-summary", response_model=ManpowerSummary)
async def project_manpower_summary(
    project_id: uuid.UUID,
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> ManpowerSummary:
    return await EmployeeService(session, actor).manpower(project_id)

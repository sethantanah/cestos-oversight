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

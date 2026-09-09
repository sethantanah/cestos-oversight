import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.db.session import get_session
from app.models import User
from app.models.location import LocationType
from app.schemas.common import Page
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate
from app.services.locations import LocationService

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=Page[LocationRead])
async def list_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    location_type: LocationType | None = None,
    project_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    actor: User = Depends(require_permission("locations.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[LocationRead]:
    return await LocationService(session, actor).list(
        page, page_size, search, location_type, project_id, is_active
    )


@router.post("", response_model=LocationRead, status_code=201)
async def create_location(
    body: LocationCreate,
    request: Request,
    actor: User = Depends(require_permission("locations.manage")),
    session: AsyncSession = Depends(get_session),
) -> LocationRead:
    return await LocationService(session, actor).create(body, request)


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    location_id: uuid.UUID,
    actor: User = Depends(require_permission("locations.read")),
    session: AsyncSession = Depends(get_session),
) -> LocationRead:
    return await LocationService(session, actor).get(location_id)


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: uuid.UUID,
    body: LocationUpdate,
    request: Request,
    actor: User = Depends(require_permission("locations.manage")),
    session: AsyncSession = Depends(get_session),
) -> LocationRead:
    return await LocationService(session, actor).update(location_id, body, request)

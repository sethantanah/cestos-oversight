import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.db.session import get_session
from app.models import User
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate
from app.schemas.common import Page
from app.services.clients import ClientService

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=Page[ClientRead])
async def list_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
    actor: User = Depends(require_permission("clients.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[ClientRead]:
    return await ClientService(session, actor).list(page, page_size, search, is_active)


@router.post("", response_model=ClientRead, status_code=201)
async def create_client(
    body: ClientCreate,
    request: Request,
    actor: User = Depends(require_permission("clients.create")),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    return await ClientService(session, actor).create(body, request)


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(
    client_id: uuid.UUID,
    actor: User = Depends(require_permission("clients.read")),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    return await ClientService(session, actor).get(client_id)


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: uuid.UUID,
    body: ClientUpdate,
    request: Request,
    actor: User = Depends(require_permission("clients.update")),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    return await ClientService(session, actor).update(client_id, body, request)

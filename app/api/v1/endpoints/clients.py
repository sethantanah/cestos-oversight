import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.db.session import get_session
from app.models import Client, User
from app.repositories.base import organization_query
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate
from app.schemas.common import Page
from app.services.audit import record_audit, request_metadata
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


@router.post("/{client_id}/logo", response_model=ClientRead)
async def upload_logo(
    client_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    actor: User = Depends(require_permission("clients.update")),
    session: AsyncSession = Depends(get_session),
) -> ClientRead:
    """Upload or replace the client logo image (PNG or JPEG)."""
    client = (
        await session.scalars(
            organization_query(Client, actor.organization_id).where(Client.id == client_id)
        )
    ).one_or_none()
    if client is None:
        raise NotFoundError("Client not found")

    storage = request.app.state.storage
    if Path(file.filename or "").suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValidationError("Upload a PNG or JPEG logo")
    data = await file.read(storage.max_bytes + 1)
    if not data:
        raise ValidationError("Logo file is empty")
    try:
        stored = await run_in_threadpool(
            storage.save,
            f"clients/{actor.organization_id}/{client_id}/logos",
            data,
            file.filename or "",
            file.content_type,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    previous = client.profile_photo_url
    try:
        client.profile_photo_url = stored.relative_path
        client.updated_by_id = actor.id
        client.updated_at = datetime.now(UTC)
        await session.flush()
        record_audit(
            session,
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            action="client.updated",
            entity_type="client",
            entity_id=client.id,
            new_values={"name": client.name, "profile_photo_url": stored.relative_path},
            **request_metadata(request),
        )
        await session.commit()
    except BaseException:
        await run_in_threadpool(storage.delete, stored.relative_path)
        raise
    if previous and previous != stored.relative_path:
        await run_in_threadpool(storage.delete, previous)
    await session.refresh(client)
    return ClientRead.model_validate(client)


@router.get("/{client_id}/logo")
async def download_logo(
    client_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_permission("clients.read")),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Download the current client logo image."""
    client = (
        await session.scalars(
            organization_query(Client, actor.organization_id).where(Client.id == client_id)
        )
    ).one_or_none()
    if client is None or not client.profile_photo_url:
        raise NotFoundError("Client logo not found")
    path = request.app.state.storage.resolve(client.profile_photo_url)
    if not path.is_file():
        raise NotFoundError("Client logo not found")
    return FileResponse(
        path, filename=Path(client.profile_photo_url).name, media_type="application/octet-stream"
    )


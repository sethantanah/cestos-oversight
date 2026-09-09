import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.db.session import get_session
from app.models import User
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserRead
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("users.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[UserRead]:
    return await UserService(session, actor).list(page, page_size)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    actor: User = Depends(require_permission("users.read")),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    return await UserService(session, actor).get(user_id)


@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    actor: User = Depends(require_permission("users.create")),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    return await UserService(session, actor).create(body, request)

import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ForbiddenError
from app.core.security import decode_access_token
from app.core.storage import LocalStorage
from app.db.session import get_session
from app.models import Role, User
from app.repositories.user import UserRepository
from app.services.organization import require_active_organization

bearer = HTTPBearer(auto_error=False)


def request_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def request_storage(request: Request) -> LocalStorage:
    return request.app.state.storage  # type: ignore[no-any-return]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(request_settings),
) -> User:
    if credentials is None:
        raise AuthenticationError("Bearer token required")
    payload = decode_access_token(credentials.credentials, settings)
    organization_id = uuid.UUID(payload["org"])
    user = await UserRepository(session, organization_id).get(uuid.UUID(payload["sub"]))
    if user is None or user.setup_required or payload.get("ver", 0) != user.token_version:
        raise AuthenticationError("User is unavailable")
    await require_active_organization(session, organization_id)
    structlog.contextvars.bind_contextvars(
        user_id=str(user.id), organization_id=str(organization_id)
    )
    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active or user.archived_at is not None:
        raise AuthenticationError("User is inactive")
    return user


def scoped_roles(user: User) -> list[Role]:
    return [
        role
        for role in user.roles
        if (role.is_system_role and role.organization_id is None)
        or role.organization_id == user.organization_id
    ]


def require_permission(code: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(user: User = Depends(get_current_active_user)) -> User:
        if not user.is_superuser and not any(
            permission.code
            in {
                code,
                {
                    "assets.meter.record": "assets.record_meter",
                    "assets.record_meter": "assets.meter.record",
                    "assets.documents.read": "asset_documents.read",
                    "asset_documents.read": "assets.documents.read",
                    "assets.documents.manage": "asset_documents.manage",
                    "asset_documents.manage": "assets.documents.manage",
                }.get(code, code),
            }
            for role in scoped_roles(user)
            for permission in role.permissions
        ):
            raise ForbiddenError("Required permission is missing")
        return user

    return dependency


def require_role(name: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(user: User = Depends(get_current_active_user)) -> User:
        if not user.is_superuser and not any(role.name == name for role in scoped_roles(user)):
            raise ForbiddenError("Required role is missing")
        return user

    return dependency

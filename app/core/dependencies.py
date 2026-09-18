import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from fastapi import Depends, Query, Request
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
    token: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(request_settings),
) -> User:
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise AuthenticationError("Bearer token required")
    payload = decode_access_token(raw_token, settings)
    organization_id = uuid.UUID(payload["org"])
    user = await UserRepository(session, organization_id).get(uuid.UUID(payload["sub"]))
    if user is None or user.setup_required or payload.get("ver", 0) != user.token_version:
        raise AuthenticationError("User is unavailable")
    await require_active_organization(session, organization_id)
    structlog.contextvars.bind_contextvars(
        user_id=str(user.id), organization_id=str(organization_id)
    )
    session.info["document_actor"] = user
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
        if user.is_superuser:
            return user
        from sqlalchemy.exc import InvalidRequestError
        try:
            user_perms = {
                permission.code
                for role in scoped_roles(user)
                for permission in role.permissions
            }
        except (InvalidRequestError, AttributeError):
            user_perms = set()
        alias = {
            "assets.meter.record": "assets.record_meter",
            "assets.record_meter": "assets.meter.record",
            "assets.documents.read": "asset_documents.read",
            "asset_documents.read": "assets.documents.read",
            "assets.documents.manage": "asset_documents.manage",
            "asset_documents.manage": "assets.documents.manage",
            "departments.manage": "employees.update",
            "positions.manage": "employees.update",
            "employees.contracts.manage": "employees.documents.manage",
            "projects.tasks.manage": "projects.update",
            "assets.assignments.manage": "assets.update",
            "assets.transfers.manage": "assets.update",
            "assets.logs.write": "assets.update",
            "projects.financials.read": "projects.read",
            "intelligence.read": "projects.read",
            "roles.manage": "users.create",
            "employees.contracts.read": "employees.documents.read",
            "employees.contracts.write": "employees.documents.manage",
            "employees.salary.write": "employees.salary.manage",
            "projects.read_assigned": "projects.read",
            "assets.read_assigned": "assets.read",
            "inventory.read_assigned": "inventory.read",
        }.get(code, code)
        if not user_perms.intersection({code, alias}):
            raise ForbiddenError("Required permission is missing")
        return user

    return dependency


def require_role(name: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(user: User = Depends(get_current_active_user)) -> User:
        if not user.is_superuser and not any(role.name == name for role in scoped_roles(user)):
            raise ForbiddenError("Required role is missing")
        return user

    return dependency

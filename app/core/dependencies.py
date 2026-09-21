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
    async def dependency(
        user: User = Depends(get_current_active_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        if user.is_superuser:
            return user

        # Bypass assets read permissions for field users, supervisors, or project-assigned employees
        if code in {
            "assets.read",
            "assets.read_assigned",
            "assets.read_assigned_only",
            "assets.documents.read",
            "asset_documents.read",
            "assets.insurance.read",
            "assets.registration.read",
            "assets.inspections.read",
            "assets.defects.read",
            "assets.media.read",
            "assets.meter.read",
            "assets.components.read",
            "assets.audit.read",
        } or (code.startswith("assets.") and any(code.endswith(s) for s in (".read", ".view", "_assigned"))):
            if getattr(user, "is_field_portal_only", False):
                return user

            roles = [r.name.lower() for r in scoped_roles(user)]
            if any(s in r for r in roles for s in ("supervisor", "manager", "foreman", "lead", "driller", "superintendent", "engineer", "operator")):
                return user

            try:
                from sqlalchemy import select, or_
                from app.models import Employee, EmployeeAssignment
                emp_id = await session.scalar(
                    select(Employee.id).where(
                        Employee.organization_id == user.organization_id,
                        Employee.user_id == user.id,
                        Employee.is_active.is_(True),
                        Employee.archived_at.is_(None),
                    )
                )
                if emp_id:
                    has_project = await session.scalar(
                        select(EmployeeAssignment.id).where(
                            EmployeeAssignment.organization_id == user.organization_id,
                            or_(
                                EmployeeAssignment.employee_id == emp_id,
                                EmployeeAssignment.supervisor_id == emp_id,
                            ),
                        ).limit(1)
                    )
                    if has_project or emp_id:
                        return user
            except Exception:
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
            "assets.read_write": "assets.update",
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

        allowed_codes = {code, alias}
        if code.startswith("assets.") or code.startswith("asset_documents."):
            asset_all = {
                "assets.read",
                "assets.read_assigned",
                "assets.read_assigned_only",
                "assets.read_write",
                "assets.update",
                "assets.manage",
                "assets.write",
                "assets.create",
                "assets.assignments.manage",
                "assets.transfers.manage",
                "assets.logs.write",
                "assets.assign",
                "assets.transfer",
            }
            if any(code.endswith(s) for s in (".read", ".view", "_assigned", "_assigned_only")) or code in {"assets.read", "assets.read_assigned", "assets.read_assigned_only"}:
                allowed_codes.update(asset_all)
            elif any(code.endswith(s) for s in (".update", ".create", ".manage", ".assign", ".transfer", ".override", ".change", ".record")):
                allowed_codes.update({"assets.manage", "assets.write", "assets.update", "assets.read_write", "assets.create", "assets.assignments.manage", "assets.transfers.manage"})
        if code == "projects.read":
            allowed_codes.update({"projects.read_assigned"})
        if code == "inventory.read":
            allowed_codes.update({"inventory.read_assigned"})
        if code == "employees.read":
            allowed_codes.update({"employees.read_assigned"})

        if not user_perms.intersection(allowed_codes):
            raise ForbiddenError("Required permission is missing")
        return user

    return dependency


def require_role(name: str) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dependency(user: User = Depends(get_current_active_user)) -> User:
        if not user.is_superuser and not any(role.name == name for role in scoped_roles(user)):
            raise ForbiddenError("Required role is missing")
        return user

    return dependency

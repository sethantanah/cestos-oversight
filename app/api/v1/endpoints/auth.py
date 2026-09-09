from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import get_current_active_user, request_settings, scoped_roles
from app.db.session import get_session
from app.models import User
from app.schemas.auth import AccessResponse, LoginRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def auth_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(request_settings),
) -> AuthService:
    return AuthService(session, settings, request)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, service: AuthService = Depends(auth_service)
) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.login(body)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, response: Response, service: AuthService = Depends(auth_service)
) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.refresh(body.refresh_token.get_secret_value())


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, service: AuthService = Depends(auth_service)) -> Response:
    await service.logout(body.refresh_token.get_secret_value())
    return Response(status_code=204)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_active_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.get("/access", response_model=AccessResponse)
async def access(user: User = Depends(get_current_active_user)) -> AccessResponse:
    roles = scoped_roles(user)
    return AccessResponse(
        roles=sorted({role.name for role in roles}),
        permissions=sorted({p.code for role in roles for p in role.permissions}),
        is_superuser=user.is_superuser,
    )

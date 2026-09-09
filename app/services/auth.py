import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import DUMMY_HASH, create_access_token, token_hash, verify_password
from app.models import RefreshToken, User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.audit import record_audit, request_metadata
from app.services.organization import require_active_organization


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, request: Request):
        self.session = session
        self.settings = settings
        self.metadata = request_metadata(request)

    def issue_tokens(self, user: User) -> TokenResponse:
        now = datetime.now(UTC)
        raw = secrets.token_urlsafe(48)
        self.session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=token_hash(raw),
                created_at=now,
                expires_at=now + timedelta(days=self.settings.refresh_token_expire_days),
                **self.metadata,
            )
        )
        return TokenResponse(
            access_token=create_access_token(
                user.id, user.organization_id, self.settings, user.token_version
            ),
            refresh_token=raw,
            expires_in=self.settings.access_token_expire_minutes * 60,
        )

    async def login(self, body: LoginRequest) -> TokenResponse:
        async with self.session.begin():
            user = await UserRepository(self.session, body.organization_id).by_email(
                str(body.email)
            )
            valid = await run_in_threadpool(
                verify_password,
                body.password.get_secret_value(),
                user.password_hash if user else DUMMY_HASH,
            )
            if (
                not valid
                or user is None
                or not user.is_active
                or user.archived_at is not None
                or user.setup_required
            ):
                raise AuthenticationError("Invalid credentials")
            await require_active_organization(self.session, user.organization_id)
            user.last_login_at = datetime.now(UTC)
            tokens = self.issue_tokens(user)
            record_audit(
                self.session,
                organization_id=user.organization_id,
                actor_user_id=user.id,
                action="LOGIN",
                entity_type="user",
                entity_id=user.id,
                **self.metadata,
            )
        return tokens

    async def refresh(self, raw: str) -> TokenResponse:
        async with self.session.begin():
            # The lock ensures concurrent reuse can only rotate a token once.
            token = await self.session.scalar(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_hash(raw))
                .with_for_update()
            )
            now = datetime.now(UTC)
            if token is None or token.revoked_at is not None or token.expires_at <= now:
                raise AuthenticationError("Invalid or expired refresh token")
            user = await self.session.get(User, token.user_id)
            if (
                user is None
                or not user.is_active
                or user.archived_at is not None
                or user.setup_required
            ):
                raise AuthenticationError("User is unavailable")
            await require_active_organization(self.session, user.organization_id)
            token.revoked_at = now
            result = self.issue_tokens(user)
        return result

    async def logout(self, raw: str) -> None:
        async with self.session.begin():
            token = await self.session.scalar(
                select(RefreshToken)
                .where(RefreshToken.token_hash == token_hash(raw))
                .with_for_update()
            )
            if token is not None and token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)
                user = await self.session.get(User, token.user_id)
                if user:
                    record_audit(
                        self.session,
                        organization_id=user.organization_id,
                        actor_user_id=user.id,
                        action="LOGOUT",
                        entity_type="user",
                        entity_id=user.id,
                        **self.metadata,
                    )

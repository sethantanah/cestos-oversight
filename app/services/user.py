import math
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserRead
from app.services.audit import record_audit, request_metadata


class UserService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor
        self.repository = UserRepository(session, actor.organization_id)

    async def list(self, page: int, page_size: int) -> Page[UserRead]:
        users, total = await self.repository.list(page, page_size)
        return Page(
            items=[UserRead.model_validate(user) for user in users],
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size),
        )

    async def get(self, user_id: uuid.UUID) -> UserRead:
        user = await self.repository.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return UserRead.model_validate(user)

    async def create(self, body: UserCreate, request: Request) -> UserRead:
        # Authentication already opened the request transaction. This use case owns its commit.
        try:
            user = User(
                organization_id=self.actor.organization_id,
                email=str(body.email),
                password_hash=await run_in_threadpool(
                    hash_password, body.password.get_secret_value()
                ),
                first_name=body.first_name,
                last_name=body.last_name,
            )
            self.session.add(user)
            await self.session.flush()
            result = UserRead.model_validate(user)
            record_audit(
                self.session,
                organization_id=self.actor.organization_id,
                actor_user_id=self.actor.id,
                action="CREATE",
                entity_type="user",
                entity_id=user.id,
                new_values={"email": user.email},
                **request_metadata(request),
            )
            await self.session.commit()
            return result
        except Exception:
            await self.session.rollback()
            raise

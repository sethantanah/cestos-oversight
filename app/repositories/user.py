import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Role, User
from app.repositories.base import organization_query


class UserRepository:
    def __init__(self, session: AsyncSession, organization_id: uuid.UUID):
        self.session = session
        self.organization_id = organization_id

    async def get(self, user_id: uuid.UUID) -> User | None:
        query = organization_query(User, self.organization_id).where(User.id == user_id)
        return (
            await self.session.scalars(
                query.options(selectinload(User.roles).selectinload(Role.permissions))
            )
        ).one_or_none()

    async def by_email(self, email: str) -> User | None:
        return (
            await self.session.scalars(
                organization_query(User, self.organization_id).where(User.email == email.lower())
            )
        ).one_or_none()

    async def list(self, page: int, page_size: int) -> tuple[list[User], int]:
        query = organization_query(User, self.organization_id)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.scalars(
            query.order_by(User.created_at, User.id).offset((page - 1) * page_size).limit(page_size)
        )
        return list(rows), total or 0

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization


async def get_organization(
    session: AsyncSession, organization_id: uuid.UUID
) -> Organization | None:
    return await session.get(Organization, organization_id)

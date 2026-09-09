import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError
from app.models import Organization
from app.repositories.organization import get_organization


async def require_active_organization(
    session: AsyncSession, organization_id: uuid.UUID
) -> Organization:
    organization = await get_organization(session, organization_id)
    if organization is None or not organization.is_active or organization.archived_at is not None:
        raise AuthenticationError("Organization is unavailable")
    return organization

"""Authenticated cross-device change detection for portal data."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import User

router = APIRouter(prefix="/sync", tags=["Data synchronization"])


@router.get("/changes")
async def get_data_changes(
    actor: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, int | str]]:
    """Return per-table revisions for this organization, never other tenants."""
    rows = await session.execute(
        text(
            """
            SELECT table_name, revision
            FROM platform_data_changes
            WHERE organization_id = :organization_id
            ORDER BY table_name
            """
        ),
        {"organization_id": actor.organization_id},
    )
    return [{"table_name": row.table_name, "revision": row.revision} for row in rows]

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.db.session import get_session
from app.models import User
from app.schemas.operations import OperationsSummary
from app.services.operations import OperationsService

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/summary", response_model=OperationsSummary)
async def operations_summary(
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
) -> OperationsSummary:
    return await OperationsService(session, actor).summary()


@router.get("/activity")
async def operations_activity(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("projects.read")),
    session: AsyncSession = Depends(get_session),
):
    return await OperationsService(session, actor).activity(page=page, page_size=page_size)

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.session import get_session
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


class DatabaseUnavailable(AppError):
    status = 503
    code = "DATABASE_UNAVAILABLE"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=HealthResponse)
async def database_health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailable("PostgreSQL is unavailable") from exc
    return HealthResponse(status="ok")

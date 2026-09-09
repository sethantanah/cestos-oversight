import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800)


async def wait_for_database(engine: AsyncEngine, attempts: int = 10) -> None:
    for attempt in range(attempts):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return
        except (OSError, SQLAlchemyError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError("PostgreSQL did not become available") from exc
            await asyncio.sleep(min(attempt + 1, 5))

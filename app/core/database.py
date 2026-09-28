import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    database_url = make_url(settings.database_url)
    # Transaction poolers can route successive transactions on one client
    # connection to different PostgreSQL sessions. Psycopg's named prepared
    # statements are session-scoped, so disable automatic preparation to avoid
    # DuplicatePreparedStatement errors when a server session is reused.
    connect_args = (
        {"prepare_threshold": None}
        if database_url.drivername == "postgresql+psycopg"
        else {
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }
    )
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=getattr(settings, "db_pool_size", 20),
        max_overflow=getattr(settings, "db_max_overflow", 30),
        pool_timeout=getattr(settings, "db_pool_timeout", 60),
        pool_recycle=1800,
        connect_args=connect_args,
    )


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

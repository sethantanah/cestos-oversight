"""Add the equipment permission catalogue without changing existing role grants."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Permission
from scripts.seed import PERMISSIONS


async def main() -> None:
    engine = build_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            existing = set((await session.scalars(select(Permission.code))).all())
            codes = [
                code
                for code in PERMISSIONS
                if code.startswith(("assets.", "asset_documents.")) and code not in existing
            ]
            session.add_all(
                [Permission(code=code, description=code.replace(".", ": ")) for code in codes]
            )
        print(f"Equipment permissions registered: {len(codes)}. Existing role grants preserved.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)

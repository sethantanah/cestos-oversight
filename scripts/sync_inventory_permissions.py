"""Register inventory permissions and add the specified defaults to existing roles."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import build_engine
from app.core.event_loop import loop_factory
from app.models import Permission, Role
from app.services.inventory_permissions import INVENTORY_PERMISSIONS, inventory_grants


async def sync(session):
    existing = {p.code: p for p in (await session.scalars(select(Permission))).all()}
    for code in INVENTORY_PERMISSIONS:
        if code not in existing:
            existing[code] = Permission(code=code, description=code.replace(".", ": "))
            session.add(existing[code])
    roles = (await session.scalars(select(Role).options(selectinload(Role.permissions)))).all()
    for role in roles:
        current = {p.code for p in role.permissions}
        role.permissions.extend(existing[code] for code in inventory_grants(role.name) - current)
    await session.flush()


async def main():
    engine = build_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            await sync(session)
        print("Inventory permission catalogue and specified role defaults synchronized.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=loop_factory)

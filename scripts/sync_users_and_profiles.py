"""Utility script to synchronize all Employee profiles and User accounts with matching email addresses."""

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.core.event_loop import loop_factory
from app.models import Employee, User


async def sync_database():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        print("Scanning database for unlinked profiles and matching user accounts...")
        unlinked_employees = (
            await session.scalars(select(Employee).where(Employee.user_id.is_(None)))
        ).all()
        synced_count = 0

        for emp in unlinked_employees:
            raw_email = emp.work_email or emp.personal_email
            if not raw_email:
                continue
            email = raw_email.lower().strip()
            user = await session.scalar(
                select(User).where(
                    User.organization_id == emp.organization_id,
                    User.email == email,
                )
            )
            if user:
                emp.user_id = user.id
                emp.work_email = email
                synced_count += 1
                print(f"Linked Employee {emp.first_name} {emp.last_name} ({email}) -> User {user.id}")

        await session.commit()
        print(f"Synchronization complete! Total profiles linked/synced: {synced_count}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(sync_database(), loop_factory=loop_factory)

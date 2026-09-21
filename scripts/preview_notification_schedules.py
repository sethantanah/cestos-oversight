"""Read-only preview of active notification schedules; never queues or sends mail."""

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.hr import NotificationSchedule
from app.services.notification_schedules import matching_alerts, recipients


async def main():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            print(
                "migration", await session.scalar(text("SELECT version_num FROM alembic_version"))
            )
            for schedule in (
                await session.scalars(
                    select(NotificationSchedule).where(NotificationSchedule.is_active.is_(True))
                )
            ).all():
                targets = await recipients(session, schedule)
                alerts = await matching_alerts(session, schedule, datetime.now(UTC).date())
                print(
                    json.dumps(
                        {
                            "title": schedule.title,
                            "eligible_recipients": len(targets),
                            "matching_records": len(alerts),
                            "last_run_at": schedule.last_run_at,
                            "next_run_at": schedule.next_run_at,
                            "messages": [message for _, message in alerts],
                        },
                        default=str,
                    )
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Notification sync remains bounded as inbox history grows."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.v1.endpoints import notifications
from app.models.hr import Notification
from app.services.notification_service import NotificationService
from app.tests.test_field_notifications import field_db  # noqa: F401


async def test_inbox_filters_and_paginates_in_sql(field_db):  # noqa: F811 - pytest fixture
    f = field_db
    stamp = datetime(2026, 9, 21, tzinfo=UTC)
    for i in range(125):
        f.session.add(Notification(
            organization_id=f.org.id, recipient_id=f.worker.id,
            message=f"Maintenance 100%_{i}", domain="EQUIPMENT", created_at=stamp,
        ))
    f.session.add_all([
        Notification(organization_id=f.org.id, recipient_id=f.worker.id,
                     message="Email only", delivery_method="EMAIL"),
        Notification(organization_id=f.org.id, recipient_id=f.supervisor.id,
                     message="Someone else's inbox"),
        Notification(organization_id=f.outsider.organization_id, recipient_id=f.worker.id,
                     message="Other tenant"),
    ])
    f.session.commit()
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(f.session.get_bind(), "before_cursor_execute", record)
    service = NotificationService(f.db, f.worker)
    first, total = await service.list_notifications(page_size=10)
    second, second_total = await service.list_notifications(page=2, page_size=10)
    assert total == second_total == 125
    assert len(first) == len(second) == 10
    assert not {row["id"] for row in first} & {row["id"] for row in second}
    assert all("LIMIT" in sql.upper() for sql in statements
               if sql.startswith("SELECT notifications."))
    assert await service.unread_count() == 125
    await service.mark_read(first[0]["id"])
    assert await service.unread_count() == 124
    matching, matched = await service.list_notifications(search="100%_", domain="equipment")
    assert len(matching) == 50 and matched == 125
    assert await service.list_notifications(search="100%_no_match") == ([], 0)
    assert await service.list_notifications(page=1000) == ([], 125)


async def test_badge_uses_only_a_count_query(field_db):  # noqa: F811 - pytest fixture
    f = field_db
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(f.session.get_bind(), "before_cursor_execute", record)
    result = await notifications.unread_notification_count(actor=f.worker, session=f.db)
    assert result == {"total": 0}
    assert len(statements) == 1
    assert "count(" in statements[0]


@pytest.mark.parametrize("endpoint", ["unread_notification_count", "list_notifications"])
async def test_sync_timeout_cancels_slow_work_without_blocking_other_tasks(monkeypatch, endpoint):
    cancelled = asyncio.Event()
    progressed = asyncio.Event()
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    async def other_request():
        await asyncio.sleep(0)
        progressed.set()
    original_timeout = asyncio.timeout
    monkeypatch.setattr(notifications.asyncio, "timeout", lambda _: original_timeout(0.02))
    method = "unread_count" if endpoint == "unread_notification_count" else "list_notifications"
    monkeypatch.setattr(NotificationService, method, slow)
    other = asyncio.create_task(other_request())
    with pytest.raises(HTTPException) as error:
        await getattr(notifications, endpoint)(actor=None, session=None)
    await other
    assert error.value.status_code == 503
    assert error.value.headers == {"Retry-After": "30"}
    assert cancelled.is_set() and progressed.is_set()

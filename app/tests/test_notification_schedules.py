"""Scheduler regression tests use isolated SQLite and never send real mail."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import ValidationError
from app.models import Asset
from app.models.employee import EmployeeDocument, EmployeeRotation
from app.models.hr import EmailDelivery, Notification, NotificationSchedule
from app.models.inventory import InventoryBalance, InventoryItem, InventoryLot
from app.services.notification_schedules import (
    evaluate,
    matching_alerts,
    next_run,
    recipients,
    run_due_schedules,
)
from app.services.notification_service import NotificationService
from app.tests.test_field_notifications import field_db  # noqa: F401

NOW = datetime(2026, 9, 20, 10, tzinfo=UTC)


@pytest.fixture
def scheduled(request):
    f = request.getfixturevalue("field_db")
    for model in [
        NotificationSchedule,
        Asset,
        EmployeeRotation,
        InventoryItem,
        InventoryLot,
        InventoryBalance,
    ]:
        model.__table__.create(f.session.get_bind())
    schedule = NotificationSchedule(
        organization_id=f.org.id,
        created_by_id=f.worker.id,
        title="CONTRACT EXPIRY",
        domain="WORKFORCE",
        rule_type="WORKFORCE_DOCUMENT_EXPIRY",
        lead_time_days=14,
        frequency="DAILY",
        delivery_method="BOTH",
        priority_tag="IMPORTANT",
        recipient_user_ids=[str(f.worker.id)],
        recipient_roles=[],
        is_active=True,
    )
    doc = EmployeeDocument(
        organization_id=f.org.id,
        employee_id=f.employee.id,
        title="Full-Time Employment Agreement",
        document_type="EMPLOYMENT_CONTRACT",
        file_url="test.pdf",
        expiry_date=NOW.date() + timedelta(days=10),
        verification_status="PENDING",
    )
    f.session.add_all([schedule, doc])
    f.session.commit()
    f.schedule, f.doc = schedule, doc
    return f


async def test_reported_contract_produces_paired_alert_and_daily_recurrence(scheduled):
    f = scheduled
    assert await evaluate(f.db, f.schedule, NOW) == 1
    alert = f.session.scalar(select(Notification))
    mail = f.session.scalar(select(EmailDelivery))
    assert alert.schedule_id == f.schedule.id
    assert alert.message == mail.message
    assert "Full-Time Employment Agreement" in alert.message
    assert "10 days" in alert.message and "2026-09-30" in alert.message
    assert await evaluate(f.db, f.schedule, NOW + timedelta(minutes=1)) == 0
    alert.is_resolved = True
    f.session.commit()
    assert await evaluate(f.db, f.schedule, NOW + timedelta(days=1)) == 1
    assert len(f.session.scalars(select(EmailDelivery)).all()) == 2


async def test_boundary_archived_rejected_and_more_than_ten(scheduled):
    f = scheduled
    for i in range(13):
        f.session.add(
            EmployeeDocument(
                organization_id=f.org.id,
                employee_id=f.employee.id,
                title=f"Permit {i}",
                file_url="test",
                expiry_date=NOW.date() + timedelta(days=14),
            )
        )
    f.session.add(
        EmployeeDocument(
            organization_id=f.org.id,
            employee_id=f.employee.id,
            title="Too early",
            file_url="test",
            expiry_date=NOW.date() + timedelta(days=15),
        )
    )
    f.doc.verification_status = "REJECTED"
    f.session.commit()
    assert await evaluate(f.db, f.schedule, NOW) == 13
    f.doc.verification_status = "PENDING"
    f.doc.is_active = False
    f.session.commit()
    assert len(await matching_alerts(f.db, f.schedule, NOW.date())) == 13


async def test_recipient_roles_union_and_no_foreign_fallback(scheduled):
    f = scheduled
    f.schedule.recipient_roles = ["Supervisor"]
    f.schedule.recipient_user_ids = [str(f.worker.id)]
    assert await recipients(f.db, f.schedule) == {f.worker.id, f.supervisor.id}
    f.schedule.recipient_user_ids = [str(f.outsider.id)]
    f.schedule.recipient_roles = []
    assert await recipients(f.db, f.schedule) == set()
    with pytest.raises(ValidationError):
        await evaluate(f.db, f.schedule, NOW)


@pytest.mark.parametrize(
    "frequency,days", [("DAILY", 1), ("EVERY_OTHER_DAY", 2), ("WEEKLY", 7), ("BIWEEKLY", 14)]
)
def test_frequency(frequency, days):
    assert next_run(NOW, frequency) == NOW + timedelta(days=days)


def test_calendar_month_and_once():
    assert next_run(datetime(2026, 1, 31, tzinfo=UTC), "MONTHLY") == datetime(
        2026, 2, 28, tzinfo=UTC
    )
    assert next_run(NOW, "ONCE") is None


@pytest.mark.parametrize(
    "method,email_count,inbox_count", [("BOTH", 1, 1), ("EMAIL", 1, 0), ("ON_PLATFORM", 0, 1)]
)
async def test_delivery_channels(scheduled, method, email_count, inbox_count):
    f = scheduled
    f.schedule.delivery_method = method
    await evaluate(f.db, f.schedule, NOW)
    assert len(f.session.scalars(select(EmailDelivery)).all()) == email_count
    _, total = await NotificationService(f.db, f.worker).list_notifications()
    assert total == inbox_count


async def test_all_supported_rules_execute_actual_sql(scheduled):
    f = scheduled
    from app.services.notification_schedules import RULES

    for rule, domain in RULES.items():
        f.schedule.rule_type = rule
        f.schedule.domain = domain
        await matching_alerts(f.db, f.schedule, NOW.date())


async def test_worker_picks_due_schedule_once_and_isolates_invalid_rule(scheduled):
    f = scheduled
    f.schedule.frequency = "ONCE"
    broken = NotificationSchedule(
        organization_id=f.org.id,
        created_by_id=f.worker.id,
        title="Invalid",
        domain="PROJECTS",
        rule_type="PROJECT_BUDGET_THRESHOLD",
        frequency="DAILY",
    )
    f.session.add(broken)
    f.session.commit()

    @asynccontextmanager
    async def factory():
        try:
            yield f.db
        except Exception:
            f.session.rollback()
            raise

    assert await run_due_schedules(factory, NOW) == 1
    assert await run_due_schedules(factory, NOW + timedelta(days=1)) == 0


async def test_failure_in_legacy_generator_does_not_starve_queue(monkeypatch):
    from app.services import field_notifications, mail, notification_schedules

    @asynccontextmanager
    async def factory():
        yield object()

    monkeypatch.setattr(
        mail, "generate_alerts", AsyncMock(side_effect=RuntimeError("broken legacy rule"))
    )
    field = AsyncMock()
    schedules = AsyncMock()
    deliver = AsyncMock(return_value=False)
    monkeypatch.setattr(field_notifications, "generate_field_alerts", field)
    monkeypatch.setattr(notification_schedules, "run_due_schedules", schedules)
    monkeypatch.setattr(mail, "deliver_one", deliver)
    await mail.scheduler_tick(
        SimpleNamespace(state=SimpleNamespace(session_factory=factory, settings=object()))
    )
    field.assert_awaited_once()
    schedules.assert_awaited_once()
    deliver.assert_awaited_once()


async def test_legacy_employee_picker_ids_resolve_to_linked_user(scheduled):
    f = scheduled
    f.schedule.recipient_user_ids = [str(f.employee.id)]
    assert await recipients(f.db, f.schedule) == {f.worker.id}
    assert await evaluate(f.db, f.schedule, NOW) == 1
    assert f.session.scalar(select(Notification)).recipient_id == f.worker.id


def test_basic_read_cannot_schedule_workforce_alerts():
    from app.services.notification_schedules import allowed_domains

    actor = SimpleNamespace(
        is_superuser=False,
        organization_id="org",
        roles=[
            SimpleNamespace(
                name="Project Manager",
                organization_id="org",
                is_system_role=False,
                permissions=[SimpleNamespace(code="employees.read_basic")],
            )
        ],
    )
    assert allowed_domains(actor) == set()
    actor.roles[0].permissions.append(SimpleNamespace(code="employees.alerts.manage"))
    assert allowed_domains(actor) == {"WORKFORCE"}


async def test_update_notification_schedule_updates_fields_and_evaluates(scheduled):
    f = scheduled
    actor = SimpleNamespace(is_superuser=True, organization_id=f.org.id, id=f.supervisor.id)
    service = NotificationService(f.db, actor)
    updated = await service.update_schedule(
        f.schedule.id,
        {
            "title": "UPDATED CONTRACT EXPIRY",
            "lead_time_days": 20,
            "frequency": "WEEKLY",
            "priority_tag": "CRITICAL",
            "delivery_method": "EMAIL",
            "recipient_user_ids": [f.worker.id],
            "is_active": True,
        },
    )
    assert updated.title == "UPDATED CONTRACT EXPIRY"
    assert updated.lead_time_days == 20
    assert updated.frequency == "WEEKLY"
    assert updated.priority_tag == "CRITICAL"
    assert updated.delivery_method == "EMAIL"
    assert updated.last_run_at is not None

    # Test invalid recipient update raises ValidationError
    with pytest.raises(ValidationError):
        await service.update_schedule(
            f.schedule.id,
            {"recipient_user_ids": [f.outsider.id], "recipient_roles": []},
        )


@pytest.mark.parametrize("rule", ["WORKFORCE_TRAINING_DUE", "WORKFORCE_TRAINING_EXPIRY"])
async def test_training_schedule_matches_real_dates_and_excludes_cancelled(scheduled, rule):
    from app.models.employee import EmployeeTrainingRecord
    f = scheduled
    f.schedule.rule_type = rule
    course = EmployeeTrainingRecord(organization_id=f.org.id, employee_id=f.employee.id,
        training_name="Safety", status="PLANNED" if rule.endswith("DUE") else "COMPLETED",
        start_date=NOW.date() + timedelta(days=2), expiry_date=NOW.date() + timedelta(days=4))
    f.session.add(course)
    f.session.commit()
    assert len(await matching_alerts(f.db, f.schedule, NOW.date())) == 1
    course.status = "CANCELLED"
    f.session.commit()
    assert await matching_alerts(f.db, f.schedule, NOW.date()) == []

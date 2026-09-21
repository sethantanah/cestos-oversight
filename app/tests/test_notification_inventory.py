"""Exercise inventory alert SQL and message rendering with actual mapped items."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session


@compiles(JSONB, "sqlite")
def sqlite_json(element, compiler, **kw):
    return "JSON"

from app.models import User
from app.models.hr import EmailDelivery, Notification, NotificationSchedule
from app.models.inventory import InventoryBalance, InventoryItem, InventoryLot, UnitOfMeasure
from app.services.notification_service import NotificationService


class AsyncAdapter:
    def __init__(self, session):
        self.session = session

    async def scalar(self, query):
        return self.session.scalar(query)

    async def scalars(self, query):
        return self.session.scalars(query)

    async def execute(self, query):
        return self.session.execute(query)

    async def get(self, model, identity):
        return self.session.get(model, identity)

    async def commit(self):
        self.session.commit()

    async def flush(self):
        self.session.flush()

    def add(self, value):
        self.session.add(value)

    def get_bind(self):
        return self.session.get_bind()


@pytest.mark.parametrize("rule", ["INVENTORY_CONSUMABLES_EXPIRY", "INVENTORY_LOW_STOCK"])
@pytest.mark.parametrize("sku", [None, "FILTER-SKU"])
async def test_create_inventory_schedule_uses_stock_totals_and_base_unit(rule, sku):
    engine = create_engine("sqlite://")
    for model in (
        User,
        UnitOfMeasure,
        InventoryItem,
        InventoryLot,
        InventoryBalance,
        NotificationSchedule,
        Notification,
        EmailDelivery,
    ):
        model.__table__.create(engine)
    org = uuid.uuid4()
    actor = User(
        id=uuid.uuid4(),
        organization_id=org,
        email="actor@example.com",
        first_name="Test",
        last_name="Actor",
        password_hash="test",
        is_superuser=True,
    )
    with Session(engine, expire_on_commit=False) as db:
        db.add(actor)
        unit = UnitOfMeasure(organization_id=org, name="Each", symbol="ea")
        db.add(unit)
        db.flush()
        item = InventoryItem(
            organization_id=org,
            item_number="ITM-00001",
            sku=sku,
            name="Filter",
            category_id=uuid.uuid4(),
            base_unit_id=unit.id,
            reorder_point=Decimal("5"),
        )
        db.add(item)
        db.flush()
        if "CONSUMABLES_EXPIRY" in rule:
            from datetime import date, timedelta
            lot = InventoryLot(
                organization_id=org,
                item_id=item.id,
                lot_number="LOT-001",
                expiry_date=date.today() + timedelta(days=5),
                status="ACTIVE",
            )
            db.add(lot)
            db.flush()
            lot_id = lot.id
        else:
            lot_id = None
        for tenant, amount in [(org, "1"), (org, "2"), (uuid.uuid4(), "100")]:
            db.add(
                InventoryBalance(
                    organization_id=tenant,
                    item_id=item.id,
                    store_id=uuid.uuid4(),
                    lot_id=lot_id,
                    quantity_on_hand=Decimal(amount),
                )
            )
        # A zero-stock item must still be returned by the stock query.
        db.add(
            InventoryItem(
                organization_id=org,
                item_number="ITM-00002",
                name="Empty",
                category_id=uuid.uuid4(),
                base_unit_id=unit.id,
                reorder_point=Decimal("5"),
            )
        )
        db.commit()

        session = AsyncAdapter(db)
        schedule = await NotificationService(session, actor).create_schedule(
            {
                "rule_type": rule,
                "delivery_method": "BOTH",
            }
        )
        from sqlalchemy import select
        notifications = list(db.scalars(select(Notification)).all())
        emails = list(db.scalars(select(EmailDelivery)).all())
        expected_count = 2 if "LOW_STOCK" in rule else 1
        assert len(notifications) == len(emails) == expected_count
        message = next(row.message for row in notifications if "Filter" in row.message)
        if "LOW_STOCK" in rule:
            assert (sku or "ITM-00001") in message
        else:
            assert "LOT-001" in message
        assert schedule.last_run_at is not None

        # Raising stock above the threshold excludes it from low-stock alerts on next period.
        if "LOW_STOCK" in rule:
            from datetime import UTC, datetime, timedelta
            db.add(
                InventoryBalance(
                    organization_id=org,
                    item_id=item.id,
                    store_id=uuid.uuid4(),
                    quantity_on_hand=Decimal("10"),
                )
            )
            db.commit()
            from app.services.notification_schedules import evaluate
            assert await evaluate(session, schedule, datetime.now(UTC) + timedelta(days=1)) == 1
    engine.dispose()

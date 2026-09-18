"""Exercise inventory alert SQL and message rendering with actual mapped items."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import User
from app.models.hr import EmailDelivery, Notification
from app.models.inventory import InventoryBalance, InventoryItem, UnitOfMeasure
from app.services.notification_service import NotificationService


@pytest.mark.parametrize("rule", ["INVENTORY_CONSUMABLES_EXPIRY", "INVENTORY_LOW_STOCK"])
@pytest.mark.parametrize("sku", [None, "FILTER-SKU"])
async def test_create_inventory_schedule_uses_stock_totals_and_base_unit(rule, sku):
    engine = create_engine("sqlite://")
    for model in (UnitOfMeasure, InventoryItem, InventoryBalance):
        model.__table__.create(engine)
    org = uuid.uuid4()
    actor = User(id=uuid.uuid4(), organization_id=org)
    with Session(engine) as db:
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
        for tenant, amount in [(org, "1"), (org, "2"), (uuid.uuid4(), "100")]:
            db.add(
                InventoryBalance(
                    organization_id=tenant,
                    item_id=item.id,
                    store_id=uuid.uuid4(),
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

        session = Mock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=db.execute)
        session.scalar = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        schedule = await NotificationService(session, actor).create_schedule(
            {
                "rule_type": rule,
                "delivery_method": "BOTH",
            }
        )
        added = [call.args[0] for call in session.add.call_args_list]
        notifications = [row for row in added if isinstance(row, Notification)]
        emails = [row for row in added if isinstance(row, EmailDelivery)]
        assert len(notifications) == len(emails) == 2
        message = next(row.message for row in notifications if "'Filter'" in row.message)
        assert (sku or "ITM-00001") in message
        assert "3.0000 ea" in message
        assert schedule.last_run_at is not None

        # Raising stock above the threshold excludes it from low-stock alerts.
        if "LOW_STOCK" in rule:
            db.add(
                InventoryBalance(
                    organization_id=org,
                    item_id=item.id,
                    store_id=uuid.uuid4(),
                    quantity_on_hand=Decimal("10"),
                )
            )
            db.commit()
            assert await NotificationService(session, actor).evaluate_schedule(schedule) == 1
    engine.dispose()

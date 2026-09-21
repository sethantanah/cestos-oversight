"""Shared field consumables persist inventory movements on the shift date."""
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models import inventory as m
from app.services import inventory
from app.services.field_consumables import ConsumptionCreate, field_consumptions, log_consumption
from app.tests.test_field_portal_records import records_db as records_fixture
from app.tests.test_field_work import field_db as field_fixture
from app.tests.test_field_work import work_db as work_fixture

field_db = field_fixture
work_db = work_fixture
records_db = records_fixture


@pytest.fixture
def consumables_db(records_db, monkeypatch):
    f = records_db
    for model in (m.InventoryItem, m.UnitOfMeasure, m.InventoryStore, m.InventoryIssue,
                  m.InventoryIssueItem, m.InventoryBalance, m.InventoryTransaction, m.InventoryLedgerEntry):
        model.__table__.create(f.session.get_bind())
    monkeypatch.setattr(inventory.InventoryService, "lock", AsyncMock())
    monkeypatch.setattr(inventory.InventoryService, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(inventory, "next_business_number", AsyncMock(side_effect=lambda *args: uuid.uuid4().hex[:20]))
    f.db.identity_map = f.session.identity_map
    f.db.refresh = AsyncMock(side_effect=lambda row, attribute_names: f.session.refresh(row, attribute_names))
    for role in f.supervisor.roles:
        set_committed_value(role, "permissions", [])
    f.unit = m.UnitOfMeasure(organization_id=f.org.id, name="Litre", symbol="L")
    f.store = m.InventoryStore(organization_id=f.org.id, name="Store", store_number="S1", location_id=uuid.uuid4())
    f.session.add_all([f.unit, f.store])
    f.session.flush()
    f.item = m.InventoryItem(organization_id=f.org.id, name="Oil", item_number="I1",
        category_id=uuid.uuid4(), base_unit_id=f.unit.id)
    f.session.add(f.item)
    f.session.flush()
    f.balance = m.InventoryBalance(organization_id=f.org.id, item_id=f.item.id, store_id=f.store.id,
        quantity_on_hand=20, inventory_value=100)
    f.session.add(f.balance)
    f.session.commit()
    return f


def payload(f, quantity=2):
    return ConsumptionCreate(project_id=f.project.id, log_date=date.today() - timedelta(days=1),
        store_id=f.store.id, submission_id=uuid.uuid4(), items=[dict(item_id=f.item.id, quantity=quantity)])


async def test_backdated_consumables_post_once_and_load_for_shift_date(consumables_db):
    f = consumables_db
    body = payload(f)
    result = await log_consumption(f.db, f.supervisor, body)
    assert result["status"] == "POSTED"
    assert f.balance.quantity_on_hand == 18
    tx = f.session.scalar(select(m.InventoryTransaction))
    assert tx.transaction_date.date() == body.log_date
    rows = await field_consumptions(f.db, f.supervisor, f.project.id, body.log_date)
    assert len(rows) == 1 and rows[0]["quantity"] == 2 and rows[0]["unit"] == "L"
    assert "total_cost" not in rows[0]
    assert await field_consumptions(f.db, f.supervisor, f.project.id, date.today()) == []
    assert await log_consumption(f.db, f.supervisor, body) == result
    assert f.balance.quantity_on_hand == 18
    await log_consumption(f.db, f.supervisor, payload(f, 3))
    assert len(await field_consumptions(f.db, f.supervisor, f.project.id, body.log_date)) == 2
    assert f.balance.quantity_on_hand == 15


async def test_insufficient_stock_rolls_back_the_entire_issue(consumables_db):
    f = consumables_db
    with pytest.raises(ConflictError, match="Insufficient"):
        await log_consumption(f.db, f.supervisor, payload(f, 21))
    assert f.session.scalar(select(m.InventoryIssue)) is None
    assert f.session.scalar(select(m.InventoryTransaction)) is None
    assert f.balance.quantity_on_hand == 20


async def test_required_approval_is_preserved(consumables_db):
    f = consumables_db
    f.item.requires_approval_to_issue = True
    f.session.commit()
    result = await log_consumption(f.db, f.supervisor, payload(f))
    assert result["status"] == "DRAFT"
    assert f.balance.quantity_on_hand == 20


async def test_consumables_respect_project_and_role_boundaries(consumables_db):
    f = consumables_db
    with pytest.raises(ForbiddenError):
        await log_consumption(f.db, f.worker, payload(f))
    with pytest.raises(NotFoundError):
        await log_consumption(f.db, f.supervisor, payload(f).model_copy(update={"project_id": f.other_project.id}))
    with pytest.raises(NotFoundError):
        await field_consumptions(f.db, f.outsider, f.project.id, date.today())

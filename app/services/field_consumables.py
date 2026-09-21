"""Project/date consumables shared by field stores and shift production reports."""
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select

from app.core.exceptions import ForbiddenError, ValidationError
from app.models.inventory import InventoryIssue, InventoryIssueItem, InventoryItem, InventoryStore, UnitOfMeasure, InventoryBalance, InventoryBin, InventoryLot, InventorySerial
from app.schemas.inventory import InventoryAction, InventoryDocumentCreate, InventoryLine
from app.services.field_equipment import require_project
from app.services.field_work import is_supervisor
from app.services.inventory import InventoryService


class ConsumptionLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    bin_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None
    serial_id: uuid.UUID | None = None


class ConsumptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    log_date: date
    store_id: uuid.UUID
    submission_id: uuid.UUID
    items: list[ConsumptionLine] = Field(min_length=1, max_length=200)


async def consumption_rows(session, organization_id, project_id, log_date):
    start = datetime.combine(log_date, time.min, UTC)
    rows = await session.execute(select(
        InventoryIssueItem.id, InventoryIssue.document_number,
        InventoryIssue.status, InventoryIssue.store_id, InventoryIssueItem.item_id,
        InventoryItem.name.label("item_name"), InventoryIssueItem.quantity,
        UnitOfMeasure.symbol.label("unit"), InventoryIssue.notes,
    ).join(InventoryIssue, InventoryIssue.id == InventoryIssueItem.document_id)
     .join(InventoryItem, InventoryItem.id == InventoryIssueItem.item_id)
     .join(UnitOfMeasure, UnitOfMeasure.id == InventoryIssueItem.unit_id)
     .where(InventoryIssue.organization_id == organization_id,
        InventoryIssueItem.organization_id == organization_id,
        InventoryItem.organization_id == organization_id,
        UnitOfMeasure.organization_id == organization_id,
        InventoryIssue.project_id == project_id,
        InventoryIssue.transaction_date >= start,
        InventoryIssue.transaction_date < start + timedelta(days=1),
        InventoryIssue.status.in_(["DRAFT", "PENDING_APPROVAL", "APPROVED", "POSTED"]))
     .order_by(InventoryIssue.transaction_date, InventoryIssueItem.id))
    return [dict(row) for row in rows.mappings()]


async def field_consumptions(session, actor, project_id, log_date):
    await require_project(session, actor, project_id)
    return await consumption_rows(session, actor.organization_id, project_id, log_date)


async def consumption_options(session, actor, project_id):
    await require_project(session, actor, project_id)
    items = await session.execute(select(InventoryItem.id, InventoryItem.name,
        UnitOfMeasure.symbol.label("unit"), InventoryItem.requires_approval_to_issue)
        .join(UnitOfMeasure, UnitOfMeasure.id == InventoryItem.base_unit_id)
        .where(InventoryItem.organization_id == actor.organization_id,
            InventoryItem.is_active.is_(True), InventoryItem.archived_at.is_(None),
            InventoryItem.is_consumable.is_(True)).order_by(InventoryItem.name))
    stores = await session.execute(select(InventoryStore.id, InventoryStore.name).where(
        InventoryStore.organization_id == actor.organization_id,
        InventoryStore.is_active.is_(True), InventoryStore.archived_at.is_(None))
        .order_by(InventoryStore.name))
    stock = await session.execute(select(InventoryBalance.id, InventoryBalance.item_id,
        InventoryBalance.store_id, InventoryBalance.bin_id, InventoryBalance.lot_id,
        InventoryBin.code.label("bin"), InventoryLot.lot_number.label("lot"),
        (InventoryBalance.quantity_on_hand - InventoryBalance.quantity_reserved - InventoryBalance.quantity_quarantined).label("available"))
        .outerjoin(InventoryBin, InventoryBin.id == InventoryBalance.bin_id)
        .outerjoin(InventoryLot, InventoryLot.id == InventoryBalance.lot_id)
        .where(InventoryBalance.organization_id == actor.organization_id, InventoryBalance.quantity_on_hand > 0))
    serials = await session.execute(select(InventorySerial.id, InventorySerial.item_id,
        InventorySerial.current_store_id.label("store_id"), InventorySerial.current_bin_id.label("bin_id"),
        InventorySerial.lot_id, InventorySerial.serial_number).where(
        InventorySerial.organization_id == actor.organization_id, InventorySerial.status == "IN_STOCK"))
    return {"items": [dict(row) for row in items.mappings()], "stores": [dict(row) for row in stores.mappings()],
        "stock": [dict(row) for row in stock.mappings()], "serials": [dict(row) for row in serials.mappings()]}


class AtomicInventoryService(InventoryService):
    async def commit(self):
        # Create and post together: invalid stock must not leave a duplicate draft behind.
        await self.session.flush()
        for row in list(self.session.identity_map.values()):
            expired = inspect(row).expired_attributes
            if expired:
                await self.session.refresh(row, attribute_names=list(expired))


async def log_consumption(session, actor, body):
    if not is_supervisor(actor):
        raise ForbiddenError("Only supervisors can log field consumables")
    await require_project(session, actor, body.project_id)
    service = AtomicInventoryService(session, actor)
    try:
        await service.lock()
        reference = f"field-consumption:{body.submission_id}"
        existing = await session.scalar(select(InventoryIssue).where(
            InventoryIssue.organization_id == actor.organization_id,
            InventoryIssue.reference_number == reference))
        if existing:
            if existing.project_id != body.project_id or existing.created_by_id != actor.id:
                raise ValidationError("This submission belongs to another consumables log")
            return {"id": existing.id, "status": existing.status}
        lines = []
        needs_approval = False
        for entry in body.items:
            item = await service.ref(InventoryItem, entry.item_id)
            if not item.is_consumable or not item.is_active or item.archived_at:
                raise ValidationError("Select an active consumable item")
            needs_approval = needs_approval or item.requires_approval_to_issue
            lines.append(InventoryLine(**entry.model_dump(), unit_id=item.base_unit_id,
                currency=item.default_currency))
        doc = await service.document_save("issues", InventoryDocumentCreate(
            project_id=body.project_id, store_id=body.store_id,
            transaction_date=datetime.combine(body.log_date, time.min, UTC),
            reference_number=reference, purpose="PROJECT_CONSUMPTION", items=lines))
        if not needs_approval:
            doc = await service.action("issues", doc["id"], "post", InventoryAction())
        await InventoryService.commit(service)
        return {"id": doc["id"], "status": doc["status"]}
    except Exception:
        await session.rollback()
        raise

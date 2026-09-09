"""Transactional inventory posting. The ledger is authoritative; balances are projections."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import delete, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import scoped_roles
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Asset, AssetCategory, Employee, Location, Project, User
from app.models import inventory as m
from app.services.audit import record_audit
from app.services.counters import next_business_number

ZERO = Decimal("0")
SCALE = Decimal("0.0001")
VALUE_SCALE = Decimal("0.00000001")
BUCKET_FIELDS = (
    "quantity_on_hand",
    "quantity_reserved",
    "quantity_quarantined",
    "quantity_in_transit",
    "inventory_value",
    "transit_value",
)
FINANCIAL = {
    "unit_cost",
    "total_cost",
    "standard_unit_cost",
    "last_unit_cost",
    "inventory_value",
    "transit_value",
    "average_unit_cost",
    "total_inventory_value",
    "total_consumption_cost",
}
MASTERS = {
    "categories": m.InventoryCategory,
    "units": m.UnitOfMeasure,
    "suppliers": m.Supplier,
    "items": m.InventoryItem,
    "conversions": m.UnitConversion,
    "stores": m.InventoryStore,
    "bins": m.InventoryBin,
    "stock-policies": m.InventoryStockPolicy,
    "item-suppliers": m.InventoryItemSupplier,
    "compatibility": m.InventoryCompatibility,
}
DOCUMENTS = {
    key: (getattr(m, "Inventory" + name), getattr(m, "Inventory" + name + "Item"), counter)
    for key, name, counter in [
        ("receipts", "Receipt", "receipt"),
        ("issues", "Issue", "issue"),
        ("returns", "Return", "return"),
        ("transfers", "Transfer", "transfer"),
        ("requests", "Request", "request"),
        ("adjustments", "Adjustment", "adjustment"),
        ("stock-counts", "StockCount", "stock_count"),
    ]
}
REFS = {
    "category_id": m.InventoryCategory,
    "parent_category_id": m.InventoryCategory,
    "base_unit_id": m.UnitOfMeasure,
    "unit_id": m.UnitOfMeasure,
    "from_unit_id": m.UnitOfMeasure,
    "to_unit_id": m.UnitOfMeasure,
    "item_id": m.InventoryItem,
    "store_id": m.InventoryStore,
    "from_store_id": m.InventoryStore,
    "to_store_id": m.InventoryStore,
    "bin_id": m.InventoryBin,
    "from_bin_id": m.InventoryBin,
    "to_bin_id": m.InventoryBin,
    "supplier_id": m.Supplier,
    "preferred_supplier_id": m.Supplier,
    "project_id": Project,
    "asset_id": Asset,
    "asset_category_id": AssetCategory,
    "employee_id": Employee,
    "manager_employee_id": Employee,
    "location_id": Location,
    "lot_id": m.InventoryLot,
    "serial_id": m.InventorySerial,
    "original_issue_id": m.InventoryIssue,
    "request_id": m.InventoryRequest,
    "reservation_id": m.InventoryReservation,
}


class InventoryService:
    def __init__(self, session: AsyncSession, actor: User):
        self.session = session
        self.actor = actor
        self.org = actor.organization_id

    def permitted(self, code: str) -> bool:
        return self.actor.is_superuser or any(
            p.code in {code, "inventory.admin"}
            for r in scoped_roles(self.actor)
            for p in r.permissions
        )

    def require(self, code: str) -> None:
        if not self.permitted(code):
            raise ForbiddenError("Required inventory permission is missing")

    async def lock(self) -> None:
        # Serialize organization-local postings, including first bucket/counter creation.
        # Deterministic 64-bit key; transaction-scoped and released on rollback/commit.
        key = int.from_bytes(self.org.bytes[:8], "big", signed=True)
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    async def ref(self, model: Any, identifier: uuid.UUID | None, lock: bool = False) -> Any:
        if identifier is None:
            return None
        query = select(model).where(model.id == identifier, model.organization_id == self.org)
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise NotFoundError("Related inventory record not found")
        return row

    def public(self, row: Any) -> Any:
        if isinstance(row, list):
            return [self.public(r) for r in row]
        if hasattr(row, "__table__"):
            row = {c.key: getattr(row, c.key) for c in inspect(type(row)).columns}
        if isinstance(row, dict):
            return {
                k: self.public(v)
                for k, v in row.items()
                if self.permitted("inventory.costs.read")
                or (k not in FINANCIAL and not k.endswith("_value_difference"))
            }
        return row

    def audit(self, action: str, row: Any, values: dict[str, Any] | None = None) -> None:
        record_audit(
            self.session,
            organization_id=self.org,
            actor_user_id=self.actor.id,
            action="inventory." + action,
            entity_type=row.__tablename__,
            entity_id=row.id,
            new_values=values or {},
        )

    async def commit(self) -> None:
        try:
            await self.session.flush()
            for row in list(self.session.identity_map.values()):
                expired = cast(Any, inspect(row)).expired_attributes
                if expired:
                    await self.session.refresh(row, attribute_names=list(expired))
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError(
                "Inventory data conflicts with an existing record or constraint"
            ) from error

    async def validate_refs(self, data: dict[str, Any], active: bool = True) -> None:
        for key, model in REFS.items():
            if data.get(key) is not None:
                row = await self.ref(model, data[key])
                if active and hasattr(row, "is_active") and not row.is_active:
                    raise ValidationError(f"{key} is archived")
                if (
                    active
                    and key == "project_id"
                    and row.status in {"CLOSED", "COMPLETED", "CANCELLED"}
                ):
                    raise ValidationError("Project is closed")
        for key, parent in [
            ("bin_id", "store_id"),
            ("from_bin_id", "from_store_id"),
            ("to_bin_id", "to_store_id"),
        ]:
            if data.get(key):
                row = await self.ref(m.InventoryBin, data[key])
                if data.get(parent) and row.store_id != data[parent]:
                    raise ValidationError("Bin belongs to another store")
        for key, model in [("lot_id", m.InventoryLot), ("serial_id", m.InventorySerial)]:
            if (
                data.get(key)
                and data.get("item_id")
                and (await self.ref(model, data[key])).item_id != data["item_id"]
            ):
                raise ValidationError("Lot or serial belongs to another item")
        for key in ("transaction_date", "expires_at", "expected_return_at"):
            when = data.get(key)
            if when is not None and when.tzinfo is None:
                raise ValidationError(f"{key} must include a timezone")
        if data.get("transaction_date") and data["transaction_date"] > datetime.now(
            UTC
        ) + timedelta(minutes=1):
            raise ValidationError("Stock movements cannot be posted in the future")

    async def master_save(self, kind: str, body: Any, identifier: uuid.UUID | None = None) -> Any:
        await self.lock()
        model = MASTERS[kind]
        data = body.model_dump(exclude_unset=identifier is not None)
        if identifier and kind == "items" and "is_active" in data:
            raise ValidationError("Use archive or restore to change item activity")
        await self.validate_refs(data)
        row: Any = (
            await self.ref(model, identifier, True)
            if identifier
            else model(organization_id=self.org, created_by_id=self.actor.id)
        )
        for key, value in data.items():
            if value is None and not inspect(model).columns[key].nullable:
                raise ValidationError(f"{key} cannot be empty")
        if kind == "categories" and data.get("parent_category_id"):
            parent = data["parent_category_id"]
            seen = {identifier}
            while parent:
                if parent in seen:
                    raise ValidationError("Category hierarchy cannot contain a cycle")
                seen.add(parent)
                parent = (await self.ref(model, parent)).parent_category_id
        if kind == "items" and identifier:
            changed = any(
                key in data and data[key] != getattr(row, key)
                for key in [
                    "base_unit_id",
                    "tracking_method",
                    "requires_batch_tracking",
                    "requires_serial_tracking",
                    "requires_expiry_tracking",
                    "default_currency",
                ]
            )
            if changed and await self.session.scalar(
                select(m.InventoryTransaction.id)
                .where(m.InventoryTransaction.item_id == identifier)
                .limit(1)
            ):
                raise ConflictError(
                    "Stocked item units, currency and tracking rules cannot be changed"
                )
        for key, value in data.items():
            setattr(row, key, value)
        if kind in {"items", "stock-policies"}:
            minimum = row.minimum_stock_level or ZERO
            maximum = row.maximum_stock_level
            if maximum is not None and maximum < minimum:
                raise ValidationError("Maximum stock must be at least minimum stock")
        if not identifier and kind in {"items", "stores"}:
            field, counter = (
                ("item_number", "item") if kind == "items" else ("store_number", "store")
            )
            setattr(
                row,
                field,
                await next_business_number(self.session, self.org, "inventory_" + counter),
            )
        row.updated_by_id = self.actor.id
        self.session.add(row)
        await self.session.flush()
        self.audit(
            ("item" if kind == "items" else kind.replace("-", "_"))
            + ("_updated" if identifier else "_created"),
            row,
        )
        await self.commit()
        return self.public(row)

    async def archive(self, kind: str, identifier: uuid.UUID, restore: bool = False) -> Any:
        await self.lock()
        row = await self.ref(MASTERS[kind], identifier, True)
        if kind == "items" and not restore:
            stock = await self.session.scalar(
                select(
                    func.sum(
                        m.InventoryBalance.quantity_on_hand + m.InventoryBalance.quantity_in_transit
                    )
                ).where(m.InventoryBalance.item_id == identifier)
            )
            if stock:
                raise ConflictError("Cannot archive an item with stock on hand or in transit")
        row.is_active = restore
        row.archived_at = None if restore else datetime.now(UTC)
        self.audit("item_restored" if restore else "item_archived", row)
        await self.commit()
        return self.public(row)

    async def quantity(self, item: Any, unit_id: uuid.UUID, quantity: Decimal) -> Decimal:
        unit = await self.ref(m.UnitOfMeasure, unit_id)
        if not unit.is_active:
            raise ValidationError("Unit is inactive")
        normalized = quantity
        if unit_id != item.base_unit_id:
            conversion = await self.session.scalar(
                select(m.UnitConversion)
                .where(
                    m.UnitConversion.organization_id == self.org,
                    m.UnitConversion.is_active.is_(True),
                    m.UnitConversion.from_unit_id == unit_id,
                    m.UnitConversion.to_unit_id == item.base_unit_id,
                    or_(m.UnitConversion.item_id == item.id, m.UnitConversion.item_id.is_(None)),
                )
                .order_by(m.UnitConversion.item_id.desc().nullslast())
                .limit(1)
            )
            if not conversion:
                raise ValidationError("No direct conversion to the item base unit")
            normalized *= conversion.conversion_factor
        precision = (await self.ref(m.UnitOfMeasure, item.base_unit_id)).precision
        if normalized <= 0 or normalized != normalized.quantize(Decimal(10) ** -precision):
            raise ValidationError("Quantity exceeds base-unit precision")
        return normalized

    async def bucket(
        self,
        item_id: uuid.UUID,
        store_id: uuid.UUID,
        bin_id: uuid.UUID | None = None,
        lot_id: uuid.UUID | None = None,
    ) -> Any:
        query = (
            select(m.InventoryBalance)
            .where(
                m.InventoryBalance.organization_id == self.org,
                m.InventoryBalance.item_id == item_id,
                m.InventoryBalance.store_id == store_id,
                m.InventoryBalance.bin_id == bin_id,
                m.InventoryBalance.lot_id == lot_id,
            )
            .with_for_update()
        )
        row = await self.session.scalar(query)
        if row is None:
            row = m.InventoryBalance(
                organization_id=self.org,
                item_id=item_id,
                store_id=store_id,
                bin_id=bin_id,
                lot_id=lot_id,
                **dict.fromkeys(BUCKET_FIELDS, ZERO),
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def effect(self, transaction: Any, bucket: Any, **deltas: Decimal) -> None:
        for field in BUCKET_FIELDS:
            value = getattr(bucket, field) + deltas.get(field, ZERO)
            setattr(bucket, field, value.quantize(VALUE_SCALE if "value" in field else SCALE))
        if (
            min(
                bucket.quantity_on_hand,
                bucket.quantity_reserved,
                bucket.quantity_quarantined,
                bucket.quantity_in_transit,
                bucket.quantity_on_hand - bucket.quantity_reserved - bucket.quantity_quarantined,
            )
            < 0
        ):
            raise ConflictError("Insufficient available stock in the selected store/bin/lot")
        self.session.add(
            m.InventoryLedgerEntry(
                organization_id=self.org,
                transaction_id=transaction.id,
                item_id=bucket.item_id,
                store_id=bucket.store_id,
                bin_id=bucket.bin_id,
                lot_id=bucket.lot_id,
                **{field: deltas.get(field, ZERO) for field in BUCKET_FIELDS},
            )
        )

    async def transaction(
        self,
        doc: Any,
        line: Any,
        kind: str,
        cost: Decimal,
        quantity: Decimal | None = None,
        key_suffix: str = "",
    ) -> Any:
        q = quantity if quantity is not None else line.normalized_quantity
        item = await self.ref(m.InventoryItem, line.item_id)
        row = m.InventoryTransaction(
            organization_id=self.org,
            transaction_number=await next_business_number(
                self.session, self.org, "inventory_transaction"
            ),
            posting_key=f"{doc.id}:{line.id}:{kind}:{key_suffix}",
            transaction_type=kind,
            item_id=line.item_id,
            quantity=q,
            unit_id=item.base_unit_id,
            normalized_quantity=q,
            from_store_id=getattr(doc, "from_store_id", None)
            or (
                getattr(doc, "store_id", None)
                if kind
                not in {
                    "OPENING_BALANCE",
                    "PURCHASE_RECEIPT",
                    "OTHER_RECEIPT",
                    "RETURN_FROM_EMPLOYEE",
                }
                else None
            ),
            to_store_id=getattr(doc, "to_store_id", None)
            or (
                getattr(doc, "store_id", None)
                if kind
                in {"OPENING_BALANCE", "PURCHASE_RECEIPT", "OTHER_RECEIPT", "RETURN_FROM_EMPLOYEE"}
                else None
            ),
            from_bin_id=getattr(line, "from_bin_id", None) or getattr(line, "bin_id", None),
            to_bin_id=getattr(line, "to_bin_id", None) or getattr(line, "bin_id", None),
            lot_id=getattr(line, "lot_id", None),
            serial_id=getattr(line, "serial_id", None),
            project_id=getattr(doc, "project_id", None),
            asset_id=getattr(doc, "asset_id", None),
            employee_id=getattr(doc, "employee_id", None),
            supplier_id=getattr(doc, "supplier_id", None),
            requested_by_id=getattr(doc, "requested_by_id", None),
            approved_by_id=getattr(doc, "approved_by_id", None),
            issued_by_id=self.actor.id,
            received_by_id=getattr(doc, "received_by_id", None),
            reference_type=doc.__tablename__,
            reference_id=doc.id,
            reference_number=getattr(doc, "document_number", None),
            future_work_order_id=getattr(doc, "future_work_order_id", None),
            unit_cost=cost,
            total_cost=(q * cost).quantize(SCALE),
            currency=item.default_currency,
            transaction_date=datetime.now(UTC),
            reason=getattr(doc, "reason", None),
            notes=getattr(doc, "notes", None),
            created_by_id=self.actor.id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def document(self, kind: str, identifier: uuid.UUID) -> Any:
        model, lines, _ = DOCUMENTS[kind]
        row = await self.ref(model, identifier)
        return {
            **self.public(row),
            "items": self.public(
                list(
                    (
                        await self.session.scalars(
                            select(lines)
                            .where(lines.document_id == identifier)
                            .order_by(lines.created_at, lines.id)
                        )
                    ).all()
                )
            ),
        }

    async def document_save(self, kind: str, body: Any, identifier: uuid.UUID | None = None) -> Any:
        await self.lock()
        model, line_model, counter = DOCUMENTS[kind]
        data = body.model_dump(exclude={"items"}, exclude_none=True)
        await self.validate_refs(data)
        if kind not in {"requests", "transfers"} and not data.get("store_id"):
            raise ValidationError("Store is required")
        if kind == "transfers" and (
            not data.get("from_store_id")
            or not data.get("to_store_id")
            or data["from_store_id"] == data["to_store_id"]
        ):
            raise ValidationError("Transfer requires two different stores")
        if kind == "adjustments" and not data.get("reason"):
            raise ValidationError("Adjustment reason is required")
        row: Any = (
            await self.ref(model, identifier, True)
            if identifier
            else model(
                organization_id=self.org,
                document_number=await next_business_number(
                    self.session, self.org, "inventory_" + counter
                ),
                created_by_id=self.actor.id,
                requested_by_id=self.actor.id,
            )
        )
        if identifier and row.status != "DRAFT":
            raise ConflictError("Only draft documents can be edited")
        for key, value in data.items():
            setattr(row, key, value)
        row.updated_by_id = self.actor.id
        self.session.add(row)
        await self.session.flush()
        if identifier:
            await self.session.execute(delete(line_model).where(line_model.document_id == row.id))
        for incoming in body.items:
            line_data = incoming.model_dump()
            await self.validate_refs({**data, **line_data})
            item = await self.ref(m.InventoryItem, incoming.item_id)
            q = await self.quantity(item, incoming.unit_id, incoming.quantity)
            if incoming.currency != item.default_currency:
                raise ValidationError("Currency must match the item valuation currency")
            if (item.requires_serial_tracking or item.tracking_method == "SERIALIZED") and q != 1:
                raise ValidationError("Serialized lines must contain exactly one base unit")
            line = line_model(
                organization_id=self.org,
                document_id=row.id,
                created_by_id=self.actor.id,
                normalized_quantity=q,
                **line_data,
            )
            self.session.add(line)
        await self.session.flush()
        self.audit(counter + "_created" if not identifier else counter + "_updated", row)
        await self.commit()
        return await self.document(kind, row.id)

    async def tracked(
        self, item: Any, line: Any, doc: Any, receipt: bool = False, allow_unavailable: bool = False
    ) -> None:
        if receipt:
            if (
                item.requires_batch_tracking
                or item.requires_expiry_tracking
                or item.tracking_method == "BATCH"
            ):
                if not line.lot_number and not line.lot_id:
                    raise ValidationError("A lot is required")
                if not line.lot_id:
                    lot = await self.session.scalar(
                        select(m.InventoryLot).where(
                            m.InventoryLot.organization_id == self.org,
                            m.InventoryLot.item_id == item.id,
                            m.InventoryLot.lot_number == line.lot_number,
                        )
                    )
                    if not lot:
                        lot = m.InventoryLot(
                            organization_id=self.org,
                            item_id=item.id,
                            lot_number=line.lot_number,
                            manufacture_date=line.manufacture_date,
                            expiry_date=line.expiry_date,
                            received_date=doc.transaction_date.date(),
                            unit_cost=line.unit_cost,
                            currency=item.default_currency,
                            supplier_id=doc.supplier_id,
                            created_by_id=self.actor.id,
                        )
                        self.session.add(lot)
                        await self.session.flush()
                    elif line.expiry_date and lot.expiry_date != line.expiry_date:
                        raise ConflictError("Lot expiry conflicts with existing batch")
                    line.lot_id = lot.id
            if item.requires_serial_tracking or item.tracking_method == "SERIALIZED":
                if not line.serial_number:
                    raise ValidationError("Serial number is required for receipt")
                if await self.session.scalar(
                    select(m.InventorySerial.id).where(
                        m.InventorySerial.organization_id == self.org,
                        m.InventorySerial.item_id == item.id,
                        m.InventorySerial.serial_number == line.serial_number,
                    )
                ):
                    raise ConflictError("Serial has already been received")
                serial = m.InventorySerial(
                    organization_id=self.org,
                    item_id=item.id,
                    serial_number=line.serial_number,
                    lot_id=line.lot_id,
                    current_store_id=doc.store_id,
                    current_bin_id=line.bin_id,
                    unit_cost=line.unit_cost,
                    supplier_id=doc.supplier_id,
                    received_at=datetime.now(UTC),
                    created_by_id=self.actor.id,
                )
                self.session.add(serial)
                await self.session.flush()
                line.serial_id = serial.id
        if (
            item.requires_batch_tracking
            or item.requires_expiry_tracking
            or item.tracking_method == "BATCH"
        ):
            if not line.lot_id:
                raise ValidationError("Select a lot for this item")
        if line.lot_id:
            lot = await self.ref(m.InventoryLot, line.lot_id)
            if lot.item_id != item.id:
                raise ValidationError("Lot belongs to another item")
            if item.requires_expiry_tracking and not lot.expiry_date:
                raise ValidationError("Expiry date is required")
            if not allow_unavailable and (
                (lot.expiry_date and lot.expiry_date < date.today()) or lot.status != "ACTIVE"
            ):
                raise ConflictError("Lot is expired or unavailable")
        if item.requires_serial_tracking or item.tracking_method == "SERIALIZED":
            if not line.serial_id:
                raise ValidationError("Select a serial number")
            serial = await self.ref(m.InventorySerial, line.serial_id, True)
            if serial.item_id != item.id or serial.lot_id != line.lot_id:
                raise ValidationError("Serial item or lot does not match")
            if (
                not receipt
                and not allow_unavailable
                and serial.status != "IN_STOCK"
                and not (getattr(doc, "reservation_id", None) and serial.status == "RESERVED")
            ):
                raise ConflictError("Serial is not available")

    async def action(self, kind: str, identifier: uuid.UUID, action: str, body: Any) -> Any:
        await self.lock()
        model, line_model, counter = DOCUMENTS[kind]
        doc = await self.ref(model, identifier, True)
        lines = list(
            (
                await self.session.scalars(
                    select(line_model)
                    .where(line_model.document_id == doc.id)
                    .order_by(line_model.item_id, line_model.id)
                )
            ).all()
        )
        terminal = {
            "post": "POSTED",
            "dispatch": "IN_TRANSIT",
            "receive": "RECEIVED",
            "approve": "APPROVED",
            "cancel": "CANCELLED",
            "submit": "SUBMITTED",
            "start": "IN_PROGRESS",
            "reject": "REJECTED",
        }
        if doc.status == terminal.get(action):
            return await self.document(kind, doc.id)
        if action == "cancel":
            if doc.status in {"POSTED", "IN_TRANSIT", "RECEIVED", "PARTIALLY_ISSUED", "FULFILLED"}:
                raise ConflictError("Posted movements require a reversal or return")
            doc.status = "CANCELLED"
        elif action == "reject":
            if kind != "requests" or doc.status not in {"SUBMITTED", "PENDING_APPROVAL"}:
                raise ConflictError("Request is not awaiting approval")
            doc.status = "REJECTED"
        elif action == "submit":
            expected = "IN_PROGRESS" if kind == "stock-counts" else "DRAFT"
            if doc.status != expected:
                raise ConflictError("Document is not ready for submission")
            if kind == "stock-counts":
                quantities = body.quantities or {}
                for line in lines:
                    value = quantities.get(line.id, line.counted_quantity)
                    if value is None or value < 0 or value != value.quantize(SCALE):
                        raise ValidationError("Provide a nonnegative count for every line")
                    line.counted_quantity = value
            doc.status = "SUBMITTED"
        elif action == "start":
            if kind != "stock-counts" or doc.status != "DRAFT":
                raise ConflictError("Count must be a draft")
            for line in lines:
                bucket = await self.bucket(line.item_id, doc.store_id, line.bin_id, line.lot_id)
                line.system_quantity = bucket.quantity_on_hand
            doc.status = "IN_PROGRESS"
        elif action == "approve":
            expected_statuses = {
                "requests": {"SUBMITTED", "PENDING_APPROVAL"},
                "stock-counts": {"SUBMITTED"},
            }.get(kind, {"DRAFT", "PENDING_APPROVAL"})
            if doc.status not in expected_statuses:
                raise ConflictError("Document is not awaiting approval")
            if kind == "requests":
                for line in lines:
                    q = (body.quantities or {}).get(line.id, line.quantity)
                    if q < 0 or q > line.quantity:
                        raise ValidationError("Approved quantity must be within requested quantity")
                    line.quantity_approved = (
                        await self.quantity(
                            await self.ref(m.InventoryItem, line.item_id), line.unit_id, q
                        )
                        if q
                        else ZERO
                    )
            doc.approved_by_id = self.actor.id
            doc.approved_at = datetime.now(UTC)
            doc.status = "APPROVED"
        elif action in {"post", "dispatch", "receive"}:
            if kind == "requests":
                raise ValidationError("Create an issue from an approved request")
            if action == "receive":
                if kind != "transfers" or doc.status != "IN_TRANSIT":
                    raise ConflictError("Transfer is not in transit")
            elif kind in {"adjustments", "stock-counts", "transfers"}:
                if doc.status != "APPROVED":
                    raise ConflictError("Approval is required before posting")
            elif doc.status not in {"DRAFT", "APPROVED"}:
                raise ConflictError("Document cannot be posted in its current state")
            await self.validate_refs({c.key: getattr(doc, c.key) for c in inspect(model).columns})
            if not lines:
                raise ValidationError("Document has no lines")
            for line in lines:
                await self.post_line(kind, doc, line, action)
            doc.status = (
                "IN_TRANSIT"
                if action == "dispatch"
                else "RECEIVED"
                if action == "receive"
                else "POSTED"
            )
            doc.posted_by_id = self.actor.id
            doc.posted_at = datetime.now(UTC)
            if action == "receive":
                doc.received_by_id = self.actor.id
                doc.received_at = datetime.now(UTC)
        else:
            raise ValidationError("Unsupported document action")
        doc.updated_by_id = self.actor.id
        if body.reason:
            doc.notes = (doc.notes or "") + "\n" + body.reason
        self.audit(
            counter
            + "_"
            + {
                "post": "posted",
                "approve": "approved",
                "dispatch": "dispatched",
                "receive": "received",
                "start": "started",
                "submit": "submitted",
                "cancel": "cancelled",
                "reject": "rejected",
            }[action],
            doc,
        )
        await self.commit()
        return await self.document(kind, doc.id)

    async def post_line(self, kind: str, doc: Any, line: Any, action: str) -> None:
        item = await self.ref(m.InventoryItem, line.item_id)
        if not item.is_active:
            raise ConflictError("Item is archived")
        q = line.normalized_quantity
        source = doc.from_store_id if kind == "transfers" else doc.store_id
        bin_id = line.from_bin_id if kind == "transfers" else line.bin_id
        await self.validate_refs(
            {
                "item_id": item.id,
                "store_id": source,
                "bin_id": bin_id,
                "lot_id": line.lot_id,
                "serial_id": line.serial_id,
            }
        )
        receipt = kind == "receipts"
        unavailable = kind in {"returns", "adjustments", "stock-counts"} or action == "receive"
        await self.tracked(item, line, doc, receipt=receipt, allow_unavailable=unavailable)
        bucket = await self.bucket(item.id, source, bin_id, line.lot_id)
        cost = (
            bucket.inventory_value / bucket.quantity_on_hand
            if bucket.quantity_on_hand
            else item.standard_unit_cost or ZERO
        )
        serial = await self.ref(m.InventorySerial, line.serial_id, True) if line.serial_id else None
        if (
            serial
            and kind in {"issues", "transfers"}
            and action != "receive"
            and (serial.current_store_id != source or serial.current_bin_id != bin_id)
        ):
            raise ConflictError("Serial is in another stock location")
        if kind == "receipts":
            if line.unit_cost is None:
                raise ValidationError("Receipt unit cost is required")
            cost = line.unit_cost * line.quantity / q
            tx = await self.transaction(
                doc,
                line,
                doc.purpose
                if doc.purpose in {"OPENING_BALANCE", "PURCHASE_RECEIPT", "OTHER_RECEIPT"}
                else "OTHER_RECEIPT",
                cost,
            )
            await self.effect(tx, bucket, quantity_on_hand=q, inventory_value=q * cost)
        elif kind == "issues":
            if item.requires_approval_to_issue and not doc.approved_by_id:
                raise ConflictError("This item requires issue approval")
            if doc.reservation_id:
                reservation = await self.ref(m.InventoryReservation, doc.reservation_id, True)
                if (
                    reservation.status != "ACTIVE"
                    or (
                        reservation.item_id,
                        reservation.store_id,
                        reservation.bin_id,
                        reservation.lot_id,
                    )
                    != (item.id, source, bin_id, line.lot_id)
                    or reservation.quantity - reservation.fulfilled_quantity < q
                ):
                    raise ConflictError("Reservation does not cover this issue")
                if reservation.expires_at and reservation.expires_at <= datetime.now(UTC):
                    raise ConflictError("Reservation has expired; release it first")
                for field in ("project_id", "asset_id"):
                    if getattr(reservation, field) and getattr(reservation, field) != getattr(
                        doc, field
                    ):
                        raise ValidationError("Reservation recipient does not match issue")
                reservation.fulfilled_quantity += q
                if reservation.fulfilled_quantity == reservation.quantity:
                    reservation.status = "FULFILLED"
            if doc.request_id:
                request = await self.ref(m.InventoryRequest, doc.request_id, True)
                if request.status not in {"APPROVED", "PARTIALLY_ISSUED"}:
                    raise ConflictError("Request is not approved")
                reqline = await self.session.scalar(
                    select(m.InventoryRequestItem)
                    .where(
                        m.InventoryRequestItem.document_id == request.id,
                        m.InventoryRequestItem.item_id == item.id,
                    )
                    .order_by(m.InventoryRequestItem.id)
                    .limit(1)
                )
                if not reqline or reqline.quantity_issued + q > (reqline.quantity_approved or ZERO):
                    raise ConflictError("Issue exceeds approved request quantity")
                reqline.quantity_issued += q
                request.status = "PARTIALLY_ISSUED"
                await self.session.flush()
                remaining = await self.session.scalar(
                    select(func.count())
                    .select_from(m.InventoryRequestItem)
                    .where(
                        m.InventoryRequestItem.document_id == request.id,
                        m.InventoryRequestItem.quantity_issued
                        < m.InventoryRequestItem.quantity_approved,
                    )
                )
                if not remaining:
                    request.status = "FULFILLED"
            tx = await self.transaction(doc, line, "ISSUE", cost)
            await self.effect(
                tx,
                bucket,
                quantity_on_hand=-q,
                quantity_reserved=-q if doc.reservation_id else ZERO,
                inventory_value=-q * cost,
            )
            if serial:
                serial.status = "ISSUED"
                serial.current_store_id = None
                serial.current_bin_id = None
                serial.assigned_asset_id = doc.asset_id
            if item.is_returnable:
                self.session.add(
                    m.InventoryCustody(
                        organization_id=self.org,
                        item_id=item.id,
                        serial_id=line.serial_id,
                        employee_id=doc.employee_id,
                        project_id=doc.project_id,
                        asset_id=doc.asset_id,
                        issue_id=doc.id,
                        quantity=q,
                        issued_at=datetime.now(UTC),
                        expected_return_at=doc.expected_return_at,
                        created_by_id=self.actor.id,
                    )
                )
        elif kind == "returns":
            if not doc.original_issue_id:
                raise ValidationError("Return must reference an original issue")
            original = await self.ref(m.InventoryIssue, doc.original_issue_id, True)
            if original.status != "POSTED":
                raise ConflictError("Original issue is not posted")
            original_tx = list(
                (
                    await self.session.scalars(
                        select(m.InventoryTransaction).where(
                            m.InventoryTransaction.reference_id == original.id,
                            m.InventoryTransaction.item_id == item.id,
                            m.InventoryTransaction.lot_id == line.lot_id,
                            m.InventoryTransaction.serial_id == line.serial_id,
                            m.InventoryTransaction.transaction_type == "ISSUE",
                        )
                    )
                ).all()
            )
            issued = sum((r.normalized_quantity for r in original_tx), ZERO)
            prior = await self.session.scalar(
                select(func.coalesce(func.sum(m.InventoryTransaction.normalized_quantity), 0))
                .join(
                    m.InventoryReturn, m.InventoryTransaction.reference_id == m.InventoryReturn.id
                )
                .where(
                    m.InventoryReturn.original_issue_id == original.id,
                    m.InventoryTransaction.item_id == item.id,
                    m.InventoryTransaction.lot_id == line.lot_id,
                    m.InventoryTransaction.serial_id == line.serial_id,
                    m.InventoryTransaction.transaction_type == "RETURN_FROM_EMPLOYEE",
                )
            )
            if not issued or q + (prior or ZERO) > issued:
                raise ConflictError("Return exceeds quantity issued")
            cost = sum((r.normalized_quantity * r.unit_cost for r in original_tx), ZERO) / issued
            doc.project_id = original.project_id
            doc.asset_id = original.asset_id
            doc.employee_id = original.employee_id
            tx = await self.transaction(doc, line, "RETURN_FROM_EMPLOYEE", cost)
            damaged = doc.condition not in {"GOOD", "USED_SERVICEABLE"}
            await self.effect(
                tx,
                bucket,
                quantity_on_hand=q,
                quantity_quarantined=q if damaged else ZERO,
                inventory_value=q * cost,
            )
            if serial:
                if serial.status not in {"ISSUED", "INSTALLED"}:
                    raise ConflictError("Serial has already been returned")
                serial.status = "QUARANTINED" if damaged else "IN_STOCK"
                serial.current_store_id = source
                serial.current_bin_id = bin_id
                serial.assigned_asset_id = None
            custody = await self.session.scalar(
                select(m.InventoryCustody).where(
                    m.InventoryCustody.issue_id == original.id,
                    m.InventoryCustody.item_id == item.id,
                    m.InventoryCustody.serial_id == line.serial_id,
                )
            )
            if custody:
                custody.returned_quantity += q
                custody.condition_at_return = doc.condition
                if custody.returned_quantity == custody.quantity:
                    custody.status = "RETURNED"
                    custody.returned_at = datetime.now(UTC)
        elif kind == "transfers":
            if action == "dispatch":
                tx = await self.transaction(doc, line, "TRANSFER_OUT", cost)
                await self.effect(
                    tx,
                    bucket,
                    quantity_on_hand=-q,
                    quantity_in_transit=q,
                    inventory_value=-q * cost,
                    transit_value=q * cost,
                )
                line.unit_cost = cost
                if serial:
                    serial.status = "IN_TRANSIT"
                    serial.current_store_id = None
                    serial.current_bin_id = None
            elif action == "receive":
                await self.validate_refs({"store_id": doc.to_store_id, "bin_id": line.to_bin_id})
                dispatched = await self.session.scalar(
                    select(m.InventoryTransaction).where(
                        m.InventoryTransaction.posting_key == f"{doc.id}:{line.id}:TRANSFER_OUT:"
                    )
                )
                if not dispatched:
                    raise ConflictError("Transfer dispatch ledger is missing")
                cost = dispatched.unit_cost
                tx = await self.transaction(doc, line, "TRANSFER_IN", cost)
                destination = await self.bucket(
                    item.id, doc.to_store_id, line.to_bin_id, line.lot_id
                )
                await self.effect(tx, bucket, quantity_in_transit=-q, transit_value=-q * cost)
                await self.effect(tx, destination, quantity_on_hand=q, inventory_value=q * cost)
                if serial:
                    serial.status = "IN_STOCK"
                    serial.current_store_id = doc.to_store_id
                    serial.current_bin_id = line.to_bin_id
            else:
                raise ValidationError("Use dispatch and receive for transfers")
        elif kind in {"adjustments", "stock-counts"}:
            purpose = doc.purpose
            if not doc.reason and kind == "adjustments":
                raise ValidationError("Adjustment reason is required")
            if kind == "stock-counts":
                if line.system_quantity != bucket.quantity_on_hand:
                    raise ConflictError("Stock changed since count started; restart the count")
                if line.counted_quantity is None:
                    raise ValidationError("Count quantity missing")
                delta = line.counted_quantity - line.system_quantity
                if not delta:
                    return
                q = abs(delta)
                txkind = "STOCK_COUNT_ADJUSTMENT"
            else:
                if purpose not in {
                    "POSITIVE_ADJUSTMENT",
                    "NEGATIVE_ADJUSTMENT",
                    "DAMAGE",
                    "LOSS",
                    "WRITE_OFF",
                    "QUARANTINE",
                    "RELEASE_FROM_QUARANTINE",
                }:
                    raise ValidationError("Select a valid adjustment purpose")
                delta = q if purpose == "POSITIVE_ADJUSTMENT" else -q
                txkind = purpose
            if delta > 0:
                cost = line.unit_cost if line.unit_cost is not None else cost
            tx = await self.transaction(doc, line, txkind, cost, quantity=q)
            if purpose == "QUARANTINE":
                await self.effect(tx, bucket, quantity_quarantined=q)
            elif purpose == "RELEASE_FROM_QUARANTINE":
                if (
                    line.lot_id
                    and (await self.ref(m.InventoryLot, line.lot_id)).expiry_date
                    and (await self.ref(m.InventoryLot, line.lot_id)).expiry_date < date.today()
                ):
                    raise ConflictError("Expired stock cannot be released")
                await self.effect(tx, bucket, quantity_quarantined=-q)
            else:
                quarantine = (
                    -min(q, bucket.quantity_quarantined)
                    if purpose in {"WRITE_OFF", "DAMAGE"}
                    else ZERO
                )
                await self.effect(
                    tx,
                    bucket,
                    quantity_on_hand=delta,
                    quantity_quarantined=quarantine,
                    inventory_value=delta * cost,
                )
            if serial:
                if purpose == "QUARANTINE":
                    serial.status = "QUARANTINED"
                elif purpose == "RELEASE_FROM_QUARANTINE":
                    serial.status = "IN_STOCK"
                elif delta < 0:
                    serial.status = "SCRAPPED"
                    serial.current_store_id = None
                else:
                    raise ValidationError(
                        "Receive or return serialized items instead of positive adjustments"
                    )
        line.unit_cost = cost
        line.total_cost = (q * cost).quantize(SCALE)
        self.audit(
            "movement_posted",
            tx,
            {"item_id": str(item.id), "document_id": str(doc.id), "type": tx.transaction_type},
        )
        await self.session.flush()

    async def reserve(self, body: Any) -> Any:
        await self.lock()
        data = body.model_dump()
        await self.validate_refs(data)
        item = await self.ref(m.InventoryItem, body.item_id)
        if body.expires_at and body.expires_at <= datetime.now(UTC):
            raise ValidationError("Reservation expiry must be in the future")
        q = await self.quantity(item, item.base_unit_id, body.quantity)
        row = m.InventoryReservation(
            organization_id=self.org,
            reservation_number=await next_business_number(
                self.session, self.org, "inventory_reservation"
            ),
            requested_by_id=self.actor.id,
            created_by_id=self.actor.id,
            **data,
        )
        self.session.add(row)
        await self.session.flush()
        await self.tracked(item, row, row)
        bucket = await self.bucket(item.id, body.store_id, body.bin_id, body.lot_id)
        tx = await self.transaction(row, row, "RESERVATION", ZERO, quantity=q)
        await self.effect(tx, bucket, quantity_reserved=q)
        if row.serial_id:
            serial = await self.ref(m.InventorySerial, row.serial_id, True)
            if (
                q != 1
                or serial.current_store_id != row.store_id
                or serial.current_bin_id != row.bin_id
            ):
                raise ValidationError("Serial does not match reservation location or quantity")
            serial.status = "RESERVED"
        self.audit("reservation_created", row, {"item_id": str(item.id)})
        await self.commit()
        return self.public(row)

    async def release(self, identifier: uuid.UUID, cancel: bool = False) -> Any:
        await self.lock()
        row = await self.ref(m.InventoryReservation, identifier, True)
        if row.status != "ACTIVE":
            return self.public(row)
        remaining = row.quantity - row.fulfilled_quantity
        tx = await self.transaction(row, row, "RESERVATION_RELEASE", ZERO, quantity=remaining)
        bucket = await self.bucket(row.item_id, row.store_id, row.bin_id, row.lot_id)
        await self.effect(tx, bucket, quantity_reserved=-remaining)
        row.status = (
            "CANCELLED"
            if cancel
            else "EXPIRED"
            if row.expires_at and row.expires_at <= datetime.now(UTC)
            else "RELEASED"
        )
        if row.serial_id:
            (await self.ref(m.InventorySerial, row.serial_id, True)).status = "IN_STOCK"
        self.audit("reservation_released", row, {"item_id": str(row.item_id)})
        await self.commit()
        return self.public(row)

    async def request_issue(self, identifier: uuid.UUID, store_id: uuid.UUID) -> Any:
        from app.schemas.inventory import InventoryDocumentCreate, InventoryLine

        await self.lock()
        request = await self.ref(m.InventoryRequest, identifier, True)
        if request.status not in {"APPROVED", "PARTIALLY_ISSUED"}:
            raise ConflictError("Request must be approved")
        existing = await self.session.scalar(
            select(m.InventoryIssue).where(
                m.InventoryIssue.request_id == identifier,
                m.InventoryIssue.status.in_(["DRAFT", "APPROVED"]),
            )
        )
        if existing:
            return await self.document("issues", existing.id)
        lines = list(
            (
                await self.session.scalars(
                    select(m.InventoryRequestItem).where(
                        m.InventoryRequestItem.document_id == identifier
                    )
                )
            ).all()
        )
        items = []
        for line in lines:
            q = (line.quantity_approved or ZERO) - line.quantity_issued
            if q > 0:
                item = await self.ref(m.InventoryItem, line.item_id)
                items.append(
                    InventoryLine(
                        item_id=item.id,
                        unit_id=item.base_unit_id,
                        quantity=q,
                        currency=item.default_currency,
                        lot_id=line.lot_id,
                        serial_id=line.serial_id,
                        bin_id=line.bin_id,
                    )
                )
        if not items:
            raise ConflictError("Request has already been fulfilled")
        return await self.document_save(
            "issues",
            InventoryDocumentCreate(
                store_id=store_id,
                request_id=request.id,
                project_id=request.project_id,
                asset_id=request.asset_id,
                employee_id=request.employee_id,
                purpose=request.purpose,
                items=items,
            ),
        )

    async def reverse(self, identifier: uuid.UUID, reason: str) -> Any:
        await self.lock()
        original = await self.ref(m.InventoryTransaction, identifier, True)
        existing = await self.session.scalar(
            select(m.InventoryTransaction).where(
                m.InventoryTransaction.reversal_of_id == identifier
            )
        )
        if existing:
            return self.public(existing)
        if original.transaction_type not in {
            "ISSUE",
            "OPENING_BALANCE",
            "PURCHASE_RECEIPT",
            "OTHER_RECEIPT",
        }:
            raise ConflictError(
                "Use a return, transfer back or approved adjustment for this movement"
            )
        later = await self.session.scalar(
            select(m.InventoryTransaction.id)
            .where(
                m.InventoryTransaction.organization_id == self.org,
                m.InventoryTransaction.item_id == original.item_id,
                m.InventoryTransaction.created_at > original.created_at,
            )
            .limit(1)
        )
        if later:
            raise ConflictError(
                "Later movements exist; use a traceable return or approved adjustment"
            )
        if original.transaction_type == "ISSUE":
            issue = await self.ref(m.InventoryIssue, original.reference_id)
            if (
                issue.reservation_id
                or issue.request_id
                or (await self.ref(m.InventoryItem, original.item_id)).is_returnable
            ):
                raise ConflictError("Use a return for requested, reserved or returnable issues")
        values = {
            c.key: getattr(original, c.key)
            for c in inspect(m.InventoryTransaction).columns
            if c.key
            not in {
                "id",
                "created_at",
                "transaction_number",
                "posting_key",
                "created_by_id",
                "transaction_date",
                "reversal_of_id",
                "reason",
                "transaction_type",
            }
        }
        row = m.InventoryTransaction(
            **values,
            transaction_number=await next_business_number(
                self.session, self.org, "inventory_transaction"
            ),
            posting_key="reversal:" + str(identifier),
            transaction_type="REVERSAL",
            reversal_of_id=identifier,
            reason=reason,
            created_by_id=self.actor.id,
            transaction_date=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        entries = list(
            (
                await self.session.scalars(
                    select(m.InventoryLedgerEntry).where(
                        m.InventoryLedgerEntry.transaction_id == identifier
                    )
                )
            ).all()
        )
        for entry in entries:
            bucket = await self.bucket(entry.item_id, entry.store_id, entry.bin_id, entry.lot_id)
            await self.effect(
                row, bucket, **{field: -getattr(entry, field) for field in BUCKET_FIELDS}
            )
        if original.serial_id:
            serial = await self.ref(m.InventorySerial, original.serial_id, True)
            if original.transaction_type == "ISSUE":
                serial.status = "IN_STOCK"
                serial.current_store_id = original.from_store_id
                serial.current_bin_id = original.from_bin_id
            else:
                serial.status = "CANCELLED"
                serial.current_store_id = None
                serial.current_bin_id = None
        self.audit(
            "transaction_reversed",
            row,
            {"item_id": str(row.item_id), "original_id": str(identifier), "reason": reason},
        )
        await self.commit()
        return self.public(row)

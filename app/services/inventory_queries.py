"""Bounded inventory queries, ledger reconstruction and deterministic forecasting."""

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased

from app.models import inventory as m
from app.models.audit_log import AuditLog
from app.services.inventory import BUCKET_FIELDS, DOCUMENTS, MASTERS, ZERO, InventoryService

LOOKBACK_DAYS = 30
DEAD_STOCK_DAYS = 180
SLOW_STOCK_DAYS = 90


class InventoryQueries(InventoryService):
    async def page(
        self, query: Any, page: int = 1, page_size: int = 50, scalars: bool = True
    ) -> dict[str, Any]:
        total = (
            await self.session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
            or 0
        )
        result = await self.session.execute(query.offset((page - 1) * page_size).limit(page_size))
        rows = (
            list(result.scalars().all())
            if scalars
            else [dict(row) for row in result.mappings().all()]
        )
        return {
            "items": self.public(rows),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, math.ceil(total / page_size)),
        }

    def stock_aggregate(self, store_id: uuid.UUID | None = None) -> Any:
        b = m.InventoryBalance
        query = select(
            b.item_id, *(func.sum(getattr(b, field)).label(field) for field in BUCKET_FIELDS)
        ).where(b.organization_id == self.org)
        if store_id:
            query = query.where(b.store_id == store_id)
        return query.group_by(b.item_id).subquery()

    def consumption_aggregate(
        self,
        days: int = LOOKBACK_DAYS,
        store_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        asset_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
    ) -> Any:
        t = m.InventoryTransaction
        original = aliased(m.InventoryTransaction)
        sign = case(
            (t.transaction_type == "ISSUE", 1),
            (t.transaction_type == "CONSUMPTION", 1),
            (t.transaction_type == "RETURN_FROM_EMPLOYEE", -1),
            (and_(t.transaction_type == "REVERSAL", original.transaction_type == "ISSUE"), -1),
            else_=0,
        )
        query = (
            select(
                t.item_id,
                func.sum(t.normalized_quantity * sign).label("consumption"),
                func.sum(t.total_cost * sign).label("total_consumption_cost"),
            )
            .outerjoin(original, t.reversal_of_id == original.id)
            .where(
                t.organization_id == self.org,
                t.transaction_date >= datetime.now(UTC) - timedelta(days=days),
            )
        )
        for col, value in [
            (t.from_store_id, store_id),
            (t.project_id, project_id),
            (t.asset_id, asset_id),
            (t.employee_id, employee_id),
        ]:
            if value:
                query = query.where(col == value)
        return query.group_by(t.item_id).subquery()

    def item_query(self, filters: dict[str, Any]) -> Any:
        item = m.InventoryItem
        b = self.stock_aggregate(filters.get("store_id"))
        c = self.consumption_aggregate(
            filters.get("days", LOOKBACK_DAYS), filters.get("store_id"), filters.get("project_id")
        )
        policy = m.InventoryStockPolicy
        onhand = func.coalesce(b.c.quantity_on_hand, 0)
        reserved = func.coalesce(b.c.quantity_reserved, 0)
        quarantine = func.coalesce(b.c.quantity_quarantined, 0)
        available = onhand - reserved - quarantine
        minimum = func.coalesce(policy.minimum_stock_level, item.minimum_stock_level)
        reorder = func.coalesce(policy.reorder_point, item.reorder_point, minimum)
        safety = func.coalesce(policy.safety_stock, item.safety_stock, 0)
        maximum = func.coalesce(policy.maximum_stock_level, item.maximum_stock_level)
        critical = or_(item.criticality == "CRITICAL", policy.is_critical.is_(True))
        status = case(
            (available <= 0, "OUT_OF_STOCK"),
            (and_(critical, available <= minimum), "CRITICAL"),
            (available <= reorder, "REORDER_REQUIRED"),
            (available < minimum, "LOW_STOCK"),
            (and_(maximum.is_not(None), available > maximum), "OVERSTOCK"),
            else_="HEALTHY",
        )
        query = (
            select(
                item.id,
                item.item_number,
                item.name,
                item.sku,
                item.category_id,
                item.base_unit_id,
                item.criticality,
                item.tracking_method,
                item.is_active,
                item.is_consumable,
                m.UnitOfMeasure.symbol.label("unit"),
                onhand.label("quantity_on_hand"),
                reserved.label("quantity_reserved"),
                quarantine.label("quantity_quarantined"),
                available.label("quantity_available"),
                func.coalesce(b.c.quantity_in_transit, 0).label("quantity_in_transit"),
                func.coalesce(b.c.inventory_value, 0).label("inventory_value"),
                func.coalesce(b.c.transit_value, 0).label("transit_value"),
                minimum.label("minimum_stock_level"),
                maximum.label("maximum_stock_level"),
                reorder.label("reorder_point"),
                safety.label("safety_stock"),
                func.coalesce(policy.reorder_quantity, item.reorder_quantity, 0).label(
                    "reorder_quantity"
                ),
                func.coalesce(policy.lead_time_days, item.lead_time_days, 0).label(
                    "lead_time_days"
                ),
                func.coalesce(c.c.consumption, 0).label("consumption"),
                func.coalesce(c.c.total_consumption_cost, 0).label("total_consumption_cost"),
                status.label("reorder_status"),
            )
            .join(m.UnitOfMeasure, item.base_unit_id == m.UnitOfMeasure.id)
            .outerjoin(b, b.c.item_id == item.id)
            .outerjoin(c, c.c.item_id == item.id)
            .outerjoin(
                policy, and_(policy.item_id == item.id, policy.store_id == filters.get("store_id"))
            )
            .where(item.organization_id == self.org)
        )
        for field in [
            "category_id",
            "criticality",
            "tracking_method",
            "is_active",
            "is_consumable",
        ]:
            if filters.get(field) is not None:
                query = query.where(getattr(item, field) == filters[field])
        if filters.get("supplier_id"):
            query = query.where(
                or_(
                    item.preferred_supplier_id == filters["supplier_id"],
                    item.id.in_(
                        select(m.InventoryItemSupplier.item_id).where(
                            m.InventoryItemSupplier.supplier_id == filters["supplier_id"],
                            m.InventoryItemSupplier.organization_id == self.org,
                        )
                    ),
                )
            )
        if filters.get("search"):
            value = "%" + filters["search"] + "%"
            query = query.where(
                or_(
                    *(
                        getattr(item, key).ilike(value)
                        for key in [
                            "item_number",
                            "sku",
                            "name",
                            "description",
                            "manufacturer",
                            "manufacturer_part_number",
                            "internal_part_number",
                            "barcode",
                            "qr_code_value",
                        ]
                    )
                )
            )
        if filters.get("item_id"):
            query = query.where(item.id == filters["item_id"])
        if filters.get("has_stock") is not None:
            query = query.where(onhand > 0 if filters["has_stock"] else onhand <= 0)
        if filters.get("low_stock"):
            query = query.where(available <= func.greatest(minimum, reorder))
        if filters.get("out_of_stock"):
            query = query.where(available <= 0)
        if filters.get("reorder_status"):
            query = query.where(status == filters["reorder_status"])
        return query.order_by(item.item_number)

    def forecast_row(self, row: dict[str, Any], days: int) -> dict[str, Any]:
        usage = max(ZERO, Decimal(row.get("consumption") or 0)) / Decimal(days)
        available = Decimal(row["quantity_available"])
        lead = Decimal(row["lead_time_days"])
        safety = Decimal(row["safety_stock"])
        remaining = available / usage if usage else None
        target = max(Decimal(row["reorder_point"]), usage * lead + safety)
        needed = max(ZERO, target - available)
        recommended = max(needed, Decimal(row["reorder_quantity"])) if needed > 0 else ZERO
        if row["maximum_stock_level"] is not None:
            recommended = min(
                recommended, max(ZERO, Decimal(row["maximum_stock_level"]) - available)
            )
        row.update(
            average_daily_consumption=usage,
            days_remaining=remaining,
            estimated_stockout_date=(
                date.today() + timedelta(days=min(36500, math.ceil(remaining)))
            )
            if remaining is not None
            else None,
            forecast_status="NO_RECENT_CONSUMPTION"
            if not usage
            else "STOCKOUT_BEFORE_SUPPLIER_LEAD_TIME"
            if remaining is not None and remaining < lead
            else "NORMAL",
            recommended_order_quantity=recommended,
            average_unit_cost=Decimal(row.get("inventory_value", 0))
            / Decimal(row["quantity_on_hand"])
            if row["quantity_on_hand"]
            else ZERO,
        )
        return row

    async def items(self, filters: dict[str, Any], page: int = 1, page_size: int = 50) -> Any:
        result = await self.page(self.item_query(filters), page, page_size, False)
        result["items"] = [
            self.public(self.forecast_row(row, filters.get("days", LOOKBACK_DAYS)))
            for row in result["items"]
        ]
        return result

    async def listing(
        self, kind: str, filters: dict[str, Any], page: int = 1, page_size: int = 50
    ) -> Any:
        model = MASTERS.get(kind) or (
            DOCUMENTS[kind][0]
            if kind in DOCUMENTS
            else {
                "lots": m.InventoryLot,
                "serials": m.InventorySerial,
                "reservations": m.InventoryReservation,
                "custody": m.InventoryCustody,
            }[kind]
        )
        query = select(model).where(model.organization_id == self.org)
        for key, value in filters.items():
            if value is not None and hasattr(model, key):
                query = query.where(getattr(model, key) == value)
        if filters.get("item_id") and kind in DOCUMENTS:
            line = DOCUMENTS[kind][1]
            query = query.where(
                model.id.in_(select(line.document_id).where(line.item_id == filters["item_id"]))
            )
        if filters.get("search"):
            cols = [
                getattr(model, key)
                for key in ["name", "code", "document_number", "lot_number", "serial_number"]
                if hasattr(model, key)
            ]
            if cols:
                query = query.where(
                    or_(*(col.ilike("%" + filters["search"] + "%") for col in cols))
                )
        return await self.page(query.order_by(model.created_at.desc(), model.id), page, page_size)

    async def stock(
        self,
        item_id: uuid.UUID | None = None,
        store_id: uuid.UUID | None = None,
        as_of: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        model: Any = m.InventoryLedgerEntry if as_of else m.InventoryBalance
        query = select(
            model.item_id,
            model.store_id,
            model.bin_id,
            model.lot_id,
            *(func.sum(getattr(model, f)).label(f) for f in BUCKET_FIELDS),
        ).where(model.organization_id == self.org)
        if as_of:
            if as_of.tzinfo is None:
                raise ValueError("Historical timestamp must include timezone")
            query = query.join(
                m.InventoryTransaction, model.transaction_id == m.InventoryTransaction.id
            ).where(m.InventoryTransaction.transaction_date <= as_of)
        if item_id:
            query = query.where(model.item_id == item_id)
        if store_id:
            query = query.where(model.store_id == store_id)
        grouped = query.group_by(
            model.item_id, model.store_id, model.bin_id, model.lot_id
        ).subquery()
        result = await self.page(
            select(
                grouped,
                m.InventoryItem.name.label("item_name"),
                m.InventoryStore.name.label("store_name"),
            )
            .join(m.InventoryItem, grouped.c.item_id == m.InventoryItem.id)
            .join(m.InventoryStore, grouped.c.store_id == m.InventoryStore.id)
            .order_by(m.InventoryItem.name, m.InventoryStore.name),
            page,
            page_size,
            False,
        )
        for row in result["items"]:
            row["quantity_available"] = (
                row["quantity_on_hand"] - row["quantity_reserved"] - row["quantity_quarantined"]
            )
            if self.permitted("inventory.costs.read"):
                row["average_unit_cost"] = (
                    row["inventory_value"] / row["quantity_on_hand"]
                    if row["quantity_on_hand"]
                    else ZERO
                )
        return result

    async def transactions(
        self, filters: dict[str, Any], page: int = 1, page_size: int = 50
    ) -> Any:
        t = m.InventoryTransaction
        query = select(t).where(t.organization_id == self.org)
        for key in [
            "item_id",
            "transaction_type",
            "project_id",
            "asset_id",
            "employee_id",
            "supplier_id",
            "transaction_number",
            "reference_number",
            "status",
        ]:
            if filters.get(key) is not None:
                query = query.where(getattr(t, key) == filters[key])
        if filters.get("category_id"):
            query = query.join(m.InventoryItem, t.item_id == m.InventoryItem.id).where(
                m.InventoryItem.category_id == filters["category_id"]
            )
        if filters.get("store_id"):
            query = query.where(
                or_(t.from_store_id == filters["store_id"], t.to_store_id == filters["store_id"])
            )
        if filters.get("date_from"):
            query = query.where(t.transaction_date >= filters["date_from"])
        if filters.get("date_to"):
            query = query.where(t.transaction_date <= filters["date_to"])
        return await self.page(query.order_by(t.transaction_date.desc(), t.id), page, page_size)

    async def reconciliation(self, page: int = 1, page_size: int = 50) -> Any:
        e = m.InventoryLedgerEntry
        b = m.InventoryBalance
        keys = ["organization_id", "item_id", "store_id", "bin_id", "lot_id"]
        ledger = (
            select(
                *(getattr(e, k) for k in keys),
                *(func.sum(getattr(e, f)).label(f) for f in BUCKET_FIELDS),
            )
            .where(e.organization_id == self.org)
            .group_by(*(getattr(e, k) for k in keys))
            .subquery()
        )
        balances = select(b).where(b.organization_id == self.org).subquery()
        join = and_(
            *(
                func.coalesce(cast(getattr(ledger.c, k), String), "")
                == func.coalesce(cast(getattr(balances.c, k), String), "")
                for k in keys
            )
        )
        diffs = [
            (
                func.coalesce(getattr(ledger.c, f), 0) - func.coalesce(getattr(balances.c, f), 0)
            ).label(f + "_difference")
            for f in BUCKET_FIELDS
        ]
        query = (
            select(
                *(
                    func.coalesce(getattr(ledger.c, k), getattr(balances.c, k)).label(k)
                    for k in keys
                ),
                *diffs,
            )
            .select_from(ledger.join(balances, join, full=True))
            .where(or_(*(expr != 0 for expr in diffs)))
            .order_by(ledger.c.item_id)
        )
        result = await self.page(query, page, page_size, False)
        result["consistent"] = result["total"] == 0
        return result

    async def overview(self, identifier: uuid.UUID) -> Any:
        item = await self.ref(m.InventoryItem, identifier)
        summary = (await self.items({"item_id": identifier}))["items"][0]
        return self.public(
            {
                "item": self.public(item),
                "category": self.public(await self.ref(m.InventoryCategory, item.category_id)),
                "base_unit": self.public(await self.ref(m.UnitOfMeasure, item.base_unit_id)),
                **summary,
                "stock": await self.stock(item_id=identifier),
                "lots": await self.listing("lots", {"item_id": identifier}),
                "supplier_options": await self.listing("item-suppliers", {"item_id": identifier}),
                "stock_policies": await self.listing("stock-policies", {"item_id": identifier}),
                "compatible_assets": await self.listing("compatibility", {"item_id": identifier}),
                "recent_transactions": await self.transactions(
                    {"item_id": identifier}, page_size=10
                ),
            }
        )

    async def activity(self, identifier: uuid.UUID, page: int = 1, page_size: int = 50) -> Any:
        await self.ref(m.InventoryItem, identifier)
        query = (
            select(AuditLog)
            .where(
                AuditLog.organization_id == self.org,
                or_(
                    AuditLog.entity_id == identifier,
                    AuditLog.new_values["item_id"].astext == str(identifier),
                ),
            )
            .order_by(AuditLog.created_at.desc())
        )
        return await self.page(query, page, page_size)

    async def dashboard(self, store_id: uuid.UUID | None = None) -> Any:
        query = self.item_query({"store_id": store_id, "is_active": True}).order_by(None).subquery()
        columns = [
            func.count().label("total_inventory_items"),
            func.coalesce(func.sum(query.c.quantity_on_hand), 0).label("total_stock_on_hand"),
            func.coalesce(func.sum(query.c.inventory_value), 0).label("total_inventory_value"),
        ]
        for label, condition in [
            ("items_in_stock", query.c.quantity_on_hand > 0),
            ("low_stock_items", query.c.quantity_available <= query.c.minimum_stock_level),
            ("out_of_stock_items", query.c.quantity_available <= 0),
            ("critical_stock_items", query.c.reorder_status == "CRITICAL"),
            ("overstock_items", query.c.reorder_status == "OVERSTOCK"),
            (
                "items_requiring_reorder",
                query.c.reorder_status.in_(["REORDER_REQUIRED", "OUT_OF_STOCK", "CRITICAL"]),
            ),
            ("quarantined_items", query.c.quantity_quarantined > 0),
        ]:
            columns.append(func.count().filter(condition).label(label))
        result = dict((await self.session.execute(select(*columns))).mappings().one())
        for kind, key, statuses in [
            ("requests", "pending_requests", ["SUBMITTED", "PENDING_APPROVAL"]),
            ("transfers", "pending_transfers", ["DRAFT", "APPROVED"]),
            ("transfers", "in_transit_transfers", ["IN_TRANSIT"]),
            ("adjustments", "pending_adjustments", ["DRAFT"]),
        ]:
            model = DOCUMENTS[kind][0]
            q = (
                select(func.count())
                .select_from(model)
                .where(model.organization_id == self.org, model.status.in_(statuses))
            )
            if store_id:
                q = q.where(
                    or_(
                        model.store_id == store_id,
                        model.from_store_id == store_id,
                        model.to_store_id == store_id,
                    )
                )
            result[key] = await self.session.scalar(q)
        result["recent_receipts"] = await self.listing(
            "receipts", {"store_id": store_id}, page_size=5
        )
        result["recent_issues"] = await self.listing("issues", {"store_id": store_id}, page_size=5)
        return self.public(result)

    async def alerts(
        self, kind: str, filters: dict[str, Any], page: int = 1, page_size: int = 50
    ) -> Any:
        if kind in {"expiring", "aging", "issue-suggestions"}:
            b = m.InventoryBalance
            lot = m.InventoryLot
            query = (
                select(
                    b.item_id,
                    b.store_id,
                    b.bin_id,
                    b.lot_id,
                    m.InventoryItem.name.label("item_name"),
                    lot.lot_number,
                    lot.expiry_date,
                    lot.received_date,
                    b.quantity_on_hand,
                    (b.quantity_on_hand - b.quantity_reserved - b.quantity_quarantined).label(
                        "quantity_available"
                    ),
                    b.inventory_value,
                )
                .join(m.InventoryItem, b.item_id == m.InventoryItem.id)
                .outerjoin(lot, b.lot_id == lot.id)
                .where(b.organization_id == self.org, b.quantity_on_hand > 0)
            )
            if filters.get("item_id"):
                query = query.where(b.item_id == filters["item_id"])
            if filters.get("store_id"):
                query = query.where(b.store_id == filters["store_id"])
            if kind == "expiring":
                query = query.where(
                    lot.expiry_date <= date.today() + timedelta(days=filters.get("days", 30))
                )
            if kind == "issue-suggestions":
                query = query.where(
                    b.quantity_on_hand > b.quantity_reserved + b.quantity_quarantined,
                    or_(
                        lot.id.is_(None),
                        and_(
                            lot.status == "ACTIVE",
                            or_(lot.expiry_date.is_(None), lot.expiry_date >= date.today()),
                        ),
                    ),
                )
            query = query.order_by(
                lot.expiry_date.asc().nullslast(), lot.received_date.asc().nullslast(), b.id
            )
            result = await self.page(query, page, page_size, False)
            for row in result["items"]:
                age = (date.today() - row["received_date"]).days if row["received_date"] else None
                row["age_days"] = age
                row["age_bucket"] = (
                    next(
                        (
                            label
                            for upper, label in [
                                (30, "0-30"),
                                (60, "31-60"),
                                (90, "61-90"),
                                (180, "91-180"),
                                (365, "181-365"),
                            ]
                            if age <= upper
                        ),
                        "365+",
                    )
                    if age is not None
                    else "UNBATCHED"
                )
            return result
        query = self.item_query(filters)
        if kind == "low-stock":
            return await self.items({**filters, "low_stock": True}, page, page_size)
        if kind == "out-of-stock":
            return await self.items({**filters, "out_of_stock": True}, page, page_size)
        if kind == "critical-stock":
            return await self.items(
                {**filters, "criticality": "CRITICAL", "low_stock": True}, page, page_size
            )
        if kind in {"dead-stock", "slow-moving"}:
            days = DEAD_STOCK_DAYS if kind == "dead-stock" else SLOW_STOCK_DAYS
            consumption = self.consumption_aggregate(days, filters.get("store_id"))
            query = query.outerjoin(consumption, consumption.c.item_id == m.InventoryItem.id).where(
                m.InventoryItem.created_at <= datetime.now(UTC) - timedelta(days=days),
                func.coalesce(consumption.c.consumption, 0)
                <= (0 if kind == "dead-stock" else days),
            )
        if kind == "reorder-recommendations":
            sub = query.order_by(None).subquery()
            query = (
                select(sub)
                .where(
                    sub.c.quantity_available
                    <= func.greatest(
                        sub.c.reorder_point,
                        sub.c.consumption
                        / filters.get("days", LOOKBACK_DAYS)
                        * sub.c.lead_time_days
                        + sub.c.safety_stock,
                    )
                )
                .order_by(sub.c.item_number)
            )
        result = await self.page(query, page, page_size, False)
        result["items"] = [
            self.public(self.forecast_row(row, filters.get("days", LOOKBACK_DAYS)))
            for row in result["items"]
        ]
        return result

    async def consumption(self, filters: dict[str, Any], page: int = 1, page_size: int = 50) -> Any:
        agg = self.consumption_aggregate(
            filters.get("days", 30),
            filters.get("store_id"),
            filters.get("project_id"),
            filters.get("asset_id"),
            filters.get("employee_id"),
        )
        query = (
            select(
                m.InventoryItem.id,
                m.InventoryItem.name,
                m.InventoryItem.item_number,
                m.InventoryItem.base_unit_id,
                agg.c.consumption,
                agg.c.total_consumption_cost,
            )
            .join(agg, agg.c.item_id == m.InventoryItem.id)
            .where(m.InventoryItem.organization_id == self.org)
        )
        if filters.get("item_id"):
            query = query.where(m.InventoryItem.id == filters["item_id"])
        if filters.get("category_id"):
            query = query.where(m.InventoryItem.category_id == filters["category_id"])
        return await self.page(
            query.order_by(agg.c.consumption.desc(), m.InventoryItem.id), page, page_size, False
        )

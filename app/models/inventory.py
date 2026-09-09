"""Inventory master data, operational documents and immutable stock ledger."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class InventoryRecord(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __abstract__ = True


class InventoryCategory(InventoryRecord, ArchiveMixin):
    __tablename__ = "inventory_categories"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    parent_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_categories.id")
    )
    is_consumable: Mapped[bool] = mapped_column(default=True)
    is_spare_part: Mapped[bool] = mapped_column(default=False)
    is_lubricant: Mapped[bool] = mapped_column(default=False)
    is_ppe: Mapped[bool] = mapped_column(default=False)
    is_tool: Mapped[bool] = mapped_column(default=False)
    is_fuel_related: Mapped[bool] = mapped_column(default=False)


class UnitOfMeasure(InventoryRecord, ArchiveMixin):
    __tablename__ = "units_of_measure"
    __table_args__ = (
        UniqueConstraint("organization_id", "symbol"),
        CheckConstraint("precision BETWEEN 0 AND 4", name="unit_precision"),
    )
    name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40), default="QUANTITY")
    precision: Mapped[int] = mapped_column(default=4)


class Supplier(InventoryRecord, ArchiveMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)


class StockPolicyFields:
    minimum_stock_level: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    maximum_stock_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reorder_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    safety_stock: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    lead_time_days: Mapped[int | None]


class InventoryItem(InventoryRecord, ArchiveMixin, StockPolicyFields):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "item_number"),
        UniqueConstraint("organization_id", "sku", name="uq_inventory_items_sku"),
        CheckConstraint(
            "minimum_stock_level >= 0 AND (standard_unit_cost IS NULL OR standard_unit_cost >= 0)",
            name="item_nonnegative",
        ),
        Index("ix_inventory_item_search", "organization_id", "name"),
    )
    item_number: Mapped[str] = mapped_column(String(30))
    sku: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_categories.id"), index=True
    )
    base_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units_of_measure.id"))
    manufacturer: Mapped[str | None] = mapped_column(String(150))
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(150))
    internal_part_number: Mapped[str | None] = mapped_column(String(150))
    barcode: Mapped[str | None] = mapped_column(String(255), index=True)
    qr_code_value: Mapped[str | None] = mapped_column(String(255), index=True)
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    standard_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    default_currency: Mapped[str] = mapped_column(String(10), default="USD")
    criticality: Mapped[str] = mapped_column(String(30), default="MEDIUM")
    tracking_method: Mapped[str] = mapped_column(String(30), default="QUANTITY")
    shelf_life_days: Mapped[int | None]
    requires_expiry_tracking: Mapped[bool] = mapped_column(default=False)
    requires_batch_tracking: Mapped[bool] = mapped_column(default=False)
    requires_serial_tracking: Mapped[bool] = mapped_column(default=False)
    requires_approval_to_issue: Mapped[bool] = mapped_column(default=False)
    is_consumable: Mapped[bool] = mapped_column(default=True)
    is_returnable: Mapped[bool] = mapped_column(default=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class UnitConversion(InventoryRecord, ArchiveMixin):
    __tablename__ = "unit_conversions"
    __table_args__ = (
        Index(
            "uq_inventory_conversion",
            "organization_id",
            "item_id",
            "from_unit_id",
            "to_unit_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "conversion_factor > 0 AND from_unit_id != to_unit_id", name="conversion_valid"
        ),
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_items.id"))
    from_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units_of_measure.id"))
    to_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units_of_measure.id"))
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class InventoryStore(InventoryRecord, ArchiveMixin):
    __tablename__ = "inventory_stores"
    __table_args__ = (UniqueConstraint("organization_id", "store_number"),)
    store_number: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    store_type: Mapped[str] = mapped_column(String(30), default="MAIN_WAREHOUSE")
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    description: Mapped[str | None] = mapped_column(Text)


class InventoryBin(InventoryRecord, ArchiveMixin):
    __tablename__ = "inventory_bins"
    __table_args__ = (UniqueConstraint("store_id", "code"),)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_stores.id"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(150))
    zone: Mapped[str | None] = mapped_column(String(50))
    aisle: Mapped[str | None] = mapped_column(String(50))
    rack: Mapped[str | None] = mapped_column(String(50))
    shelf: Mapped[str | None] = mapped_column(String(50))
    bin: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)


class InventoryStockPolicy(InventoryRecord, StockPolicyFields):
    __tablename__ = "inventory_stock_policies"
    __table_args__ = (
        UniqueConstraint("item_id", "store_id"),
        CheckConstraint("minimum_stock_level >= 0", name="policy_nonnegative"),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_stores.id"), index=True)
    is_critical: Mapped[bool] = mapped_column(default=False)


class InventoryLot(InventoryRecord):
    __tablename__ = "inventory_lots"
    __table_args__ = (
        UniqueConstraint("organization_id", "item_id", "lot_number"),
        CheckConstraint("expiry_date >= manufacture_date", name="lot_dates"),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    lot_number: Mapped[str] = mapped_column(String(100))
    supplier_batch_number: Mapped[str | None] = mapped_column(String(100))
    manufacture_date: Mapped[date | None]
    expiry_date: Mapped[date | None] = mapped_column(index=True)
    received_date: Mapped[date | None]
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(10))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    notes: Mapped[str | None] = mapped_column(Text)


class InventorySerial(InventoryRecord):
    __tablename__ = "inventory_serials"
    __table_args__ = (UniqueConstraint("organization_id", "item_id", "serial_number"),)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    serial_number: Mapped[str] = mapped_column(String(150), index=True)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"))
    current_store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_stores.id"))
    current_bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    status: Mapped[str] = mapped_column(String(30), default="IN_STOCK")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    assigned_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class InventoryItemSupplier(InventoryRecord, ArchiveMixin):
    __tablename__ = "inventory_item_suppliers"
    __table_args__ = (UniqueConstraint("item_id", "supplier_id"),)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    supplier_item_code: Mapped[str | None] = mapped_column(String(100))
    supplier_description: Mapped[str | None] = mapped_column(Text)
    last_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(10))
    lead_time_days: Mapped[int | None]
    minimum_order_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    is_preferred: Mapped[bool] = mapped_column(default=False)
    last_purchase_date: Mapped[date | None]


class InventoryCompatibility(InventoryRecord):
    __tablename__ = "inventory_item_asset_compatibility"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    asset_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_categories.id"))
    manufacturer: Mapped[str | None] = mapped_column(String(150))
    model: Mapped[str | None] = mapped_column(String(150))
    notes: Mapped[str | None] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(default=False)


class DocumentFields:
    document_number: Mapped[str] = mapped_column(String(30))
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_stores.id"), index=True
    )
    from_store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_stores.id"))
    to_store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_stores.id"))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), index=True)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    posted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    purpose: Mapped[str] = mapped_column(String(40), default="OTHER")
    condition: Mapped[str] = mapped_column(String(30), default="GOOD")
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(String(100))
    original_issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_issues.id"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_requests.id"))
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_reservations.id")
    )
    future_work_order_id: Mapped[uuid.UUID | None]
    purchase_order_id: Mapped[uuid.UUID | None]
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now().astimezone()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needed_by_date: Mapped[date | None]
    priority: Mapped[str] = mapped_column(String(30), default="NORMAL")
    count_type: Mapped[str] = mapped_column(String(30), default="SPOT")


class LineFields:
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units_of_measure.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    normalized_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    from_bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    to_bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"))
    serial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_serials.id"))
    lot_number: Mapped[str | None] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(150))
    expiry_date: Mapped[date | None]
    manufacture_date: Mapped[date | None]
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    system_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    counted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    quantity_approved: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    quantity_issued: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class InventoryReceipt(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_receipts"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryReceiptItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_receipt_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="receipts_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_receipts.id"), index=True)


class InventoryIssue(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_issues"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryIssueItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_issue_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="issues_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_issues.id"), index=True)


class InventoryReturn(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_returns"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryReturnItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_return_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="returns_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_returns.id"), index=True)


class InventoryTransfer(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_transfers"
    __table_args__ = (
        UniqueConstraint("organization_id", "document_number"),
        CheckConstraint("from_store_id != to_store_id", name="transfer_distinct"),
    )


class InventoryTransferItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_transfer_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="transfers_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_transfers.id"), index=True)


class InventoryRequest(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_requests"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryRequestItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_request_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="requests_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_requests.id"), index=True)


class InventoryAdjustment(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_adjustments"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryAdjustmentItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_adjustment_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="adjustments_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_adjustments.id"), index=True
    )


class InventoryStockCount(InventoryRecord, DocumentFields):
    __tablename__ = "inventory_stock_counts"
    __table_args__ = (UniqueConstraint("organization_id", "document_number"),)


class InventoryStockCountItem(InventoryRecord, LineFields):
    __tablename__ = "inventory_stock_count_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="stock_counts_positive"),)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_stock_counts.id"), index=True
    )


class InventoryReservation(InventoryRecord):
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        UniqueConstraint("organization_id", "reservation_number"),
        CheckConstraint(
            "quantity > 0 AND fulfilled_quantity >= 0 AND fulfilled_quantity <= quantity",
            name="reservation_quantity",
        ),
    )
    reservation_number: Mapped[str] = mapped_column(String(30))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_stores.id"), index=True)
    bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"))
    serial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_serials.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    fulfilled_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    reserved_for_date: Mapped[date | None]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class InventoryCustody(InventoryRecord):
    __tablename__ = "inventory_custody"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND returned_quantity >= 0 AND returned_quantity <= quantity",
            name="custody_quantity",
        ),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    serial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_serials.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_issues.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    condition_at_issue: Mapped[str] = mapped_column(String(30), default="GOOD")
    condition_at_return: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="ISSUED")
    notes: Mapped[str | None] = mapped_column(Text)


class InventoryTransaction(UUIDMixin, OrganizationMixin, Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        UniqueConstraint("organization_id", "transaction_number"),
        UniqueConstraint("organization_id", "posting_key", name="uq_inventory_posting_key"),
        CheckConstraint("quantity > 0 AND normalized_quantity > 0", name="transaction_positive"),
    )
    transaction_number: Mapped[str] = mapped_column(String(30))
    posting_key: Mapped[str] = mapped_column(String(200))
    transaction_type: Mapped[str] = mapped_column(String(40), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units_of_measure.id"))
    normalized_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    from_store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_stores.id"), index=True
    )
    to_store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_stores.id"), index=True
    )
    from_bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    to_bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"))
    serial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_serials.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppliers.id"))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reference_type: Mapped[str] = mapped_column(String(50))
    reference_id: Mapped[uuid.UUID]
    reference_number: Mapped[str | None] = mapped_column(String(100))
    future_work_order_id: Mapped[uuid.UUID | None]
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_transactions.id"), unique=True
    )
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(10))
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="POSTED")
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class BalanceFields:
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_stores.id"), index=True)
    bin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_bins.id"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_lots.id"))
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    quantity_quarantined: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    quantity_in_transit: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    inventory_value: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    transit_value: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)


class InventoryBalance(UUIDMixin, OrganizationMixin, TimestampMixin, BalanceFields, Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        Index(
            "uq_inventory_balance_bucket",
            "organization_id",
            "item_id",
            "store_id",
            "bin_id",
            "lot_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "quantity_on_hand >= 0 AND quantity_reserved >= 0 AND "
            "quantity_quarantined >= 0 AND quantity_in_transit >= 0 AND "
            "quantity_on_hand >= quantity_reserved + quantity_quarantined",
            name="balance_nonnegative",
        ),
    )


class InventoryLedgerEntry(UUIDMixin, OrganizationMixin, BalanceFields, Base):
    """Signed stock/value effects. Immutable alongside the parent transaction."""

    __tablename__ = "inventory_ledger_entries"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_transactions.id"), index=True
    )


class InventoryImport(InventoryRecord):
    __tablename__ = "inventory_imports"
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="PREVIEW")
    filename: Mapped[str] = mapped_column(String(255))
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

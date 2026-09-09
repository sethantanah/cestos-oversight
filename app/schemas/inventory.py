"""Validated inventory API contracts; server-owned posting state is never writable."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InventoryCategoryCreate(InventoryInput):
    name: str = Field(..., max_length=150, min_length=1)
    code: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=10000)
    parent_category_id: uuid.UUID | None = Field(None)
    is_consumable: bool = Field(True)
    is_spare_part: bool = Field(False)
    is_lubricant: bool = Field(False)
    is_ppe: bool = Field(False)
    is_tool: bool = Field(False)
    is_fuel_related: bool = Field(False)
    is_active: bool = Field(True)


class InventoryCategoryUpdate(InventoryInput):
    name: str | None = Field(None, max_length=150, min_length=1)
    code: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=10000)
    parent_category_id: uuid.UUID | None = Field(None)
    is_consumable: bool | None = Field(None)
    is_spare_part: bool | None = Field(None)
    is_lubricant: bool | None = Field(None)
    is_ppe: bool | None = Field(None)
    is_tool: bool | None = Field(None)
    is_fuel_related: bool | None = Field(None)
    is_active: bool | None = Field(None)


class UnitOfMeasureCreate(InventoryInput):
    name: str = Field(..., max_length=100, min_length=1)
    symbol: str = Field(..., max_length=20, min_length=1)
    category: str = Field("QUANTITY", max_length=40, min_length=1)
    precision: int = Field(4, ge=0, le=4)
    is_active: bool = Field(True)


class UnitOfMeasureUpdate(InventoryInput):
    name: str | None = Field(None, max_length=100, min_length=1)
    symbol: str | None = Field(None, max_length=20, min_length=1)
    category: str | None = Field(None, max_length=40, min_length=1)
    precision: int | None = Field(None, ge=0, le=4)
    is_active: bool | None = Field(None)


class SupplierCreate(InventoryInput):
    name: str = Field(..., max_length=200, min_length=1)
    contact_name: str | None = Field(None, max_length=150)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=10000)
    is_active: bool = Field(True)


class SupplierUpdate(InventoryInput):
    name: str | None = Field(None, max_length=200, min_length=1)
    contact_name: str | None = Field(None, max_length=150)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=10000)
    is_active: bool | None = Field(None)


class InventoryItemCreate(InventoryInput):
    sku: str | None = Field(None, max_length=100)
    name: str = Field(..., max_length=200, min_length=1)
    description: str | None = Field(None, max_length=10000)
    category_id: uuid.UUID = Field(...)
    base_unit_id: uuid.UUID = Field(...)
    manufacturer: str | None = Field(None, max_length=150)
    manufacturer_part_number: str | None = Field(None, max_length=150)
    internal_part_number: str | None = Field(None, max_length=150)
    barcode: str | None = Field(None, max_length=255)
    qr_code_value: str | None = Field(None, max_length=255)
    preferred_supplier_id: uuid.UUID | None = Field(None)
    standard_unit_cost: Decimal | None = Field(None, ge=0)
    default_currency: str = Field("USD", max_length=10, min_length=1)
    criticality: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        "MEDIUM", max_length=30, min_length=1
    )
    tracking_method: Literal["QUANTITY", "BATCH", "SERIALIZED"] = Field(
        "QUANTITY", max_length=30, min_length=1
    )
    shelf_life_days: int | None = Field(None, ge=0)
    requires_expiry_tracking: bool = Field(False)
    requires_batch_tracking: bool = Field(False)
    requires_serial_tracking: bool = Field(False)
    requires_approval_to_issue: bool = Field(False)
    is_consumable: bool = Field(True)
    is_returnable: bool = Field(False)
    image_url: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=10000)
    is_active: bool = Field(True)
    minimum_stock_level: Decimal = Field(Decimal("0"), ge=0)
    maximum_stock_level: Decimal | None = Field(None, ge=0)
    reorder_point: Decimal | None = Field(None, ge=0)
    reorder_quantity: Decimal | None = Field(None, ge=0)
    safety_stock: Decimal | None = Field(None, ge=0)
    lead_time_days: int | None = Field(None, ge=0)


class InventoryItemUpdate(InventoryInput):
    sku: str | None = Field(None, max_length=100)
    name: str | None = Field(None, max_length=200, min_length=1)
    description: str | None = Field(None, max_length=10000)
    category_id: uuid.UUID | None = Field(None)
    base_unit_id: uuid.UUID | None = Field(None)
    manufacturer: str | None = Field(None, max_length=150)
    manufacturer_part_number: str | None = Field(None, max_length=150)
    internal_part_number: str | None = Field(None, max_length=150)
    barcode: str | None = Field(None, max_length=255)
    qr_code_value: str | None = Field(None, max_length=255)
    preferred_supplier_id: uuid.UUID | None = Field(None)
    standard_unit_cost: Decimal | None = Field(None, ge=0)
    default_currency: str | None = Field(None, max_length=10, min_length=1)
    criticality: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = Field(
        None, max_length=30, min_length=1
    )
    tracking_method: Literal["QUANTITY", "BATCH", "SERIALIZED"] | None = Field(
        None, max_length=30, min_length=1
    )
    shelf_life_days: int | None = Field(None, ge=0)
    requires_expiry_tracking: bool | None = Field(None)
    requires_batch_tracking: bool | None = Field(None)
    requires_serial_tracking: bool | None = Field(None)
    requires_approval_to_issue: bool | None = Field(None)
    is_consumable: bool | None = Field(None)
    is_returnable: bool | None = Field(None)
    image_url: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=10000)
    is_active: bool | None = Field(None)
    minimum_stock_level: Decimal | None = Field(None, ge=0)
    maximum_stock_level: Decimal | None = Field(None, ge=0)
    reorder_point: Decimal | None = Field(None, ge=0)
    reorder_quantity: Decimal | None = Field(None, ge=0)
    safety_stock: Decimal | None = Field(None, ge=0)
    lead_time_days: int | None = Field(None, ge=0)


class UnitConversionCreate(InventoryInput):
    item_id: uuid.UUID | None = Field(None)
    from_unit_id: uuid.UUID = Field(...)
    to_unit_id: uuid.UUID = Field(...)
    conversion_factor: Decimal = Field(..., gt=0)
    is_active: bool = Field(True)


class UnitConversionUpdate(InventoryInput):
    item_id: uuid.UUID | None = Field(None)
    from_unit_id: uuid.UUID | None = Field(None)
    to_unit_id: uuid.UUID | None = Field(None)
    conversion_factor: Decimal | None = Field(None, gt=0)
    is_active: bool | None = Field(None)


class InventoryStoreCreate(InventoryInput):
    name: str = Field(..., max_length=200, min_length=1)
    location_id: uuid.UUID = Field(...)
    store_type: Literal[
        "MAIN_WAREHOUSE",
        "PROJECT_STORE",
        "WORKSHOP_STORE",
        "CONTAINER_STORE",
        "MOBILE_STORE",
        "OTHER",
    ] = Field("MAIN_WAREHOUSE", max_length=30, min_length=1)
    manager_employee_id: uuid.UUID | None = Field(None)
    description: str | None = Field(None, max_length=10000)
    is_active: bool = Field(True)


class InventoryStoreUpdate(InventoryInput):
    name: str | None = Field(None, max_length=200, min_length=1)
    location_id: uuid.UUID | None = Field(None)
    store_type: (
        Literal[
            "MAIN_WAREHOUSE",
            "PROJECT_STORE",
            "WORKSHOP_STORE",
            "CONTAINER_STORE",
            "MOBILE_STORE",
            "OTHER",
        ]
        | None
    ) = Field(None, max_length=30, min_length=1)
    manager_employee_id: uuid.UUID | None = Field(None)
    description: str | None = Field(None, max_length=10000)
    is_active: bool | None = Field(None)


class InventoryBinCreate(InventoryInput):
    store_id: uuid.UUID = Field(...)
    code: str = Field(..., max_length=50, min_length=1)
    name: str | None = Field(None, max_length=150)
    zone: str | None = Field(None, max_length=50)
    aisle: str | None = Field(None, max_length=50)
    rack: str | None = Field(None, max_length=50)
    shelf: str | None = Field(None, max_length=50)
    bin: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=10000)
    is_active: bool = Field(True)


class InventoryBinUpdate(InventoryInput):
    store_id: uuid.UUID | None = Field(None)
    code: str | None = Field(None, max_length=50, min_length=1)
    name: str | None = Field(None, max_length=150)
    zone: str | None = Field(None, max_length=50)
    aisle: str | None = Field(None, max_length=50)
    rack: str | None = Field(None, max_length=50)
    shelf: str | None = Field(None, max_length=50)
    bin: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=10000)
    is_active: bool | None = Field(None)


class InventoryStockPolicyCreate(InventoryInput):
    item_id: uuid.UUID = Field(...)
    store_id: uuid.UUID = Field(...)
    is_critical: bool = Field(False)
    minimum_stock_level: Decimal = Field(Decimal("0"), ge=0)
    maximum_stock_level: Decimal | None = Field(None, ge=0)
    reorder_point: Decimal | None = Field(None, ge=0)
    reorder_quantity: Decimal | None = Field(None, ge=0)
    safety_stock: Decimal | None = Field(None, ge=0)
    lead_time_days: int | None = Field(None, ge=0)


class InventoryStockPolicyUpdate(InventoryInput):
    item_id: uuid.UUID | None = Field(None)
    store_id: uuid.UUID | None = Field(None)
    is_critical: bool | None = Field(None)
    minimum_stock_level: Decimal | None = Field(None, ge=0)
    maximum_stock_level: Decimal | None = Field(None, ge=0)
    reorder_point: Decimal | None = Field(None, ge=0)
    reorder_quantity: Decimal | None = Field(None, ge=0)
    safety_stock: Decimal | None = Field(None, ge=0)
    lead_time_days: int | None = Field(None, ge=0)


class InventoryItemSupplierCreate(InventoryInput):
    item_id: uuid.UUID = Field(...)
    supplier_id: uuid.UUID = Field(...)
    supplier_item_code: str | None = Field(None, max_length=100)
    supplier_description: str | None = Field(None, max_length=10000)
    last_unit_cost: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=10)
    lead_time_days: int | None = Field(None, ge=0)
    minimum_order_quantity: Decimal | None = Field(None, ge=0)
    is_preferred: bool = Field(False)
    last_purchase_date: date | None = Field(None)
    is_active: bool = Field(True)


class InventoryItemSupplierUpdate(InventoryInput):
    item_id: uuid.UUID | None = Field(None)
    supplier_id: uuid.UUID | None = Field(None)
    supplier_item_code: str | None = Field(None, max_length=100)
    supplier_description: str | None = Field(None, max_length=10000)
    last_unit_cost: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=10)
    lead_time_days: int | None = Field(None, ge=0)
    minimum_order_quantity: Decimal | None = Field(None, ge=0)
    is_preferred: bool | None = Field(None)
    last_purchase_date: date | None = Field(None)
    is_active: bool | None = Field(None)


class InventoryCompatibilityCreate(InventoryInput):
    item_id: uuid.UUID = Field(...)
    asset_id: uuid.UUID | None = Field(None)
    asset_category_id: uuid.UUID | None = Field(None)
    manufacturer: str | None = Field(None, max_length=150)
    model: str | None = Field(None, max_length=150)
    notes: str | None = Field(None, max_length=10000)
    is_verified: bool = Field(False)


class InventoryCompatibilityUpdate(InventoryInput):
    item_id: uuid.UUID | None = Field(None)
    asset_id: uuid.UUID | None = Field(None)
    asset_category_id: uuid.UUID | None = Field(None)
    manufacturer: str | None = Field(None, max_length=150)
    model: str | None = Field(None, max_length=150)
    notes: str | None = Field(None, max_length=10000)
    is_verified: bool | None = Field(None)


class InventoryLine(InventoryInput):
    item_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    bin_id: uuid.UUID | None = None
    from_bin_id: uuid.UUID | None = None
    to_bin_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None
    serial_id: uuid.UUID | None = None
    lot_number: str | None = Field(None, max_length=100)
    serial_number: str | None = Field(None, max_length=150)
    expiry_date: date | None = None
    manufacture_date: date | None = None
    unit_cost: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=4)
    currency: str = Field("USD", min_length=3, max_length=10)
    counted_quantity: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=4)
    notes: str | None = Field(None, max_length=10000)


class InventoryDocumentCreate(InventoryInput):
    store_id: uuid.UUID | None = None
    from_store_id: uuid.UUID | None = None
    to_store_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    original_issue_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    future_work_order_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    reference_number: str | None = Field(None, max_length=100)
    transaction_date: datetime | None = None
    expected_return_at: datetime | None = None
    needed_by_date: date | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT", "CRITICAL"] = "NORMAL"
    purpose: Literal[
        "OTHER",
        "OPENING_BALANCE",
        "PURCHASE_RECEIPT",
        "OTHER_RECEIPT",
        "PROJECT_CONSUMPTION",
        "ASSET_CONSUMPTION",
        "MAINTENANCE",
        "EMPLOYEE_USE",
        "PPE",
        "TOOLS",
        "OFFICE_USE",
        "CAMP_USE",
        "POSITIVE_ADJUSTMENT",
        "NEGATIVE_ADJUSTMENT",
        "DAMAGE",
        "LOSS",
        "WRITE_OFF",
        "QUARANTINE",
        "RELEASE_FROM_QUARANTINE",
    ] = "OTHER"
    condition: Literal[
        "GOOD", "USED_SERVICEABLE", "DAMAGED", "DEFECTIVE", "QUARANTINE", "SCRAP"
    ] = "GOOD"
    count_type: Literal["FULL", "CYCLE", "SPOT"] = "SPOT"
    reason: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=10000)
    items: list[InventoryLine] = Field(min_length=1, max_length=200)


class InventoryReservationCreate(InventoryInput):
    item_id: uuid.UUID
    store_id: uuid.UUID
    bin_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None
    serial_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    reserved_for_date: date | None = None
    expires_at: datetime | None = None
    notes: str | None = Field(None, max_length=10000)


class InventoryAction(InventoryInput):
    reason: str | None = Field(None, max_length=10000)
    store_id: uuid.UUID | None = None
    quantities: dict[uuid.UUID, Decimal] | None = None


class InventoryReverse(InventoryInput):
    reason: str = Field(min_length=1, max_length=10000)

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.procurement import PoStatus


class PurchaseOrderItemCreate(BaseModel):
    inventory_item_id: uuid.UUID | None = None
    item_name: str | None = Field(default=None, max_length=200)
    description: str = Field(..., min_length=1, max_length=255)
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class PurchaseOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_order_id: uuid.UUID
    inventory_item_id: uuid.UUID | None = None
    item_name: str | None = None
    description: str
    quantity_ordered: float
    quantity_received: float
    unit_price: float
    total_price: float


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    category: str | None = Field(default=None, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(default_factory=list)
    save_as_draft: bool = False

    @model_validator(mode="after")
    def require_supplier(self):
        if not self.supplier_id and not (self.supplier_name and self.supplier_name.strip()):
            raise ValueError("Select or enter a supplier")
        return self


class PurchaseOrderUpdate(BaseModel):
    supplier_name: str = Field(..., min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    category: str | None = Field(default=None, max_length=100)
    total_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(default_factory=list)


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    project_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    category: str | None = None
    status: PoStatus
    total_amount: float
    currency: str
    notes: str | None = None
    items: list[PurchaseOrderItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by_name: str | None = None
    expense_raised: bool = False
    expense_status: str | None = None
    expense_total_amount: float = 0
    expense_paid_amount: float = 0
    expense_balance_due: float = 0
    expense_payments: list[dict] = Field(default_factory=list)
    attachment_file_name: str | None = None
    attachment_mime_type: str | None = None
    attachment_size_bytes: int | None = None
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None


class ReceiveGoodsRequest(BaseModel):
    item_receipts: dict[uuid.UUID, Decimal]  # maps item_id -> quantity_received

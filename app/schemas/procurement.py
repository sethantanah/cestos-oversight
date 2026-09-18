import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.procurement import PoStatus


class PurchaseOrderItemCreate(BaseModel):
    inventory_item_id: uuid.UUID | None = None
    description: str = Field(..., min_length=1, max_length=255)
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class PurchaseOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_order_id: uuid.UUID
    inventory_item_id: uuid.UUID | None = None
    description: str
    quantity_ordered: float
    quantity_received: float
    unit_price: float
    total_price: float


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID
    project_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    currency: str = Field("USD", min_length=3, max_length=3)
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(default_factory=list)


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    project_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None
    status: PoStatus
    total_amount: float
    currency: str
    notes: str | None = None
    items: list[PurchaseOrderItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReceiveGoodsRequest(BaseModel):
    item_receipts: dict[uuid.UUID, Decimal]  # maps item_id -> quantity_received

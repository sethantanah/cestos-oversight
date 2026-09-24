import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ExpenseItem(BaseModel):
    inventory_item_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=250)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)

class OperationalExpenseCreate(BaseModel):
    purchase_order_id: uuid.UUID | None = None
    payee_id: uuid.UUID | None = None
    pay_to_name: str = Field(min_length=1, max_length=200)
    pay_to_phone: str | None = Field(default=None, max_length=50)
    bank_account_details: str | None = Field(default=None, max_length=1000)
    expense_date: date
    payment_method: Literal["CASH", "BANK_TRANSFER", "MOBILE_MONEY", "CARD", "OTHER"]
    items: list[ExpenseItem] = Field(default_factory=list, max_length=100)
    total_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    manual_total: bool = False

class OperationalExpenseUpdate(BaseModel):
    pay_to_name: str | None = Field(default=None, min_length=1, max_length=200)
    expense_date: date | None = None
    total_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    payment_method: Literal["CASH", "BANK_TRANSFER", "MOBILE_MONEY", "CARD", "OTHER"] | None = None
    invoice_name: str | None = Field(default=None, max_length=255)

class OperationalExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    expense_number: str
    submitted_by_id: uuid.UUID
    purchase_order_id: uuid.UUID | None = None
    purchase_order_number: str | None = None
    payee_id: uuid.UUID | None
    pay_to_name: str
    pay_to_phone: str | None
    bank_account_details: str | None
    expense_date: date
    payment_method: str
    items: list[dict[str, Any]]
    total_cost: Decimal
    paid_amount: Decimal = Decimal("0")
    balance_due: Decimal | None = None
    payments: list[dict[str, Any]] = Field(default_factory=list)
    payment_history_missing: bool = False
    status: str
    invoice_name: str | None
    receipt_name: str | None
    paid_by_id: uuid.UUID | None
    paid_at: datetime | None
    extraction_status: str
    extracted_data: dict[str, Any]
    created_at: datetime

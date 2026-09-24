import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FuelLogCreate(Input):
    project_id: uuid.UUID | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fuel_type: Literal["DIESEL", "PETROL", "OTHER"] = "DIESEL"
    quantity_litres: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    meter_reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    supplier: str | None = Field(default=None, max_length=200)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=20000)


class FuelDeliveryCreate(Input):
    project_id: uuid.UUID
    site_location_id: uuid.UUID
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fuel_type: Literal["DIESEL", "PETROL", "OTHER"] = "DIESEL"
    quantity_litres: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    supplier: str | None = Field(default=None, max_length=200)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=20000)

    @field_validator("recorded_at")
    @classmethod
    def past_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value > datetime.now(UTC):
            raise ValueError("Choose a timestamp with timezone that is not in the future")
        return value


class MaintenanceChecklistItem(Input):
    id: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=500)
    completed: bool = False
class FuelDeliveryUpdate(Input):
    recorded_at: datetime | None = None
    fuel_type: Literal["DIESEL", "PETROL", "OTHER"] | None = None
    quantity_litres: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    supplier: str | None = Field(default=None, max_length=200)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=20000)


class FuelAllocationCreate(Input):
    project_id: uuid.UUID
    site_location_id: uuid.UUID
    asset_id: uuid.UUID
    delivery_id: uuid.UUID | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    quantity_litres: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    notes: str | None = Field(default=None, max_length=20000)

    @field_validator("recorded_at", mode="before")
    @classmethod
    def past_time(cls, value: Any) -> datetime:
        if isinstance(value, str):
            v_str = value.strip()
            if len(v_str) == 10:
                v_str = f"{v_str}T12:00:00Z"
            elif not v_str.endswith("Z") and "+" not in v_str and "-" not in v_str[10:]:
                v_str = f"{v_str}Z"
            value = datetime.fromisoformat(v_str.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            if value > datetime.now(UTC) + timedelta(minutes=10):
                raise ValueError("Choose a timestamp that is not in the future")
        return value


class FuelAllocationUpdate(Input):
    asset_id: uuid.UUID | None = None
    delivery_id: uuid.UUID | None = None
    recorded_at: datetime | None = None
    quantity_litres: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    notes: str | None = Field(default=None, max_length=20000)

    @field_validator("recorded_at", mode="before")
    @classmethod
    def past_time(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            v_str = value.strip()
            if len(v_str) == 10:
                v_str = f"{v_str}T12:00:00Z"
            elif not v_str.endswith("Z") and "+" not in v_str and "-" not in v_str[10:]:
                v_str = f"{v_str}Z"
            value = datetime.fromisoformat(v_str.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            if value > datetime.now(UTC) + timedelta(minutes=10):
                raise ValueError("Choose a timestamp that is not in the future")
        return value
class MaintenanceCreate(Input):
    checklist: list[MaintenanceChecklistItem] = Field(default_factory=list, max_length=100)
    asset_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    maintenance_type: Literal["PREVENTIVE", "CORRECTIVE", "INSPECTION", "SERVICE", "OTHER"] = (
        "SERVICE"
    )
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    scheduled_date: date | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    provider: str | None = Field(default=None, max_length=200)
    cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    assigned_employee_id: uuid.UUID | None = None
    is_recurring: bool = False
    recurrence_interval_days: int | None = Field(default=None, ge=1, le=365)


class MaintenanceStatus(Input):
    status: Literal["IN_PROGRESS", "COMPLETED", "CANCELLED"]
    notes: str = Field(min_length=1, max_length=20000)


class ProjectNoteCreate(Input):
    record_type: Literal["NOTE", "COMMENT"] = "NOTE"
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)


class RetireAsset(Input):
    reason: str = Field(min_length=1, max_length=20000)


class FuelLogUpdate(Input):
    project_id: uuid.UUID | None = None
    recorded_at: datetime | None = None
    fuel_type: Literal["DIESEL", "PETROL", "OTHER"] | None = None
    quantity_litres: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    meter_reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    supplier: str | None = Field(default=None, max_length=200)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=20000)


class MaintenanceUpdate(Input):
    project_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    maintenance_type: (
        Literal["PREVENTIVE", "CORRECTIVE", "INSPECTION", "SERVICE", "OTHER"] | None
    ) = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] | None = None
    scheduled_date: date | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    provider: str | None = Field(default=None, max_length=200)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: Literal["OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED"] | None = None
    completion_notes: str | None = Field(default=None, max_length=20000)
    assigned_employee_id: uuid.UUID | None = None
    is_recurring: bool | None = None
    recurrence_interval_days: int | None = Field(default=None, ge=1, le=365)


class FuelReductionCreate(Input):
    fuel_log_id: uuid.UUID | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    litres_reduced: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    remaining_litres: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=3)
    reduction_reason: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=20000)


class InspectionUpdate(Input):
    inspection_type: str | None = Field(default=None, max_length=40)
    inspection_date: datetime | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    condition_status: str | None = Field(default=None, max_length=30)
    summary: str | None = Field(default=None, max_length=20000)
    defects_found: bool | None = None
    defect_notes: str | None = Field(default=None, max_length=20000)
    follow_up_required: bool | None = None


class MeterReadingUpdate(Input):
    reading: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    recorded_at: datetime | None = None
    reading_type: Literal["HOURS", "ODOMETER", "MILES", "NONE"] | None = None
    source: str | None = Field(default=None, max_length=50)
    project_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=20000)
    is_correction: bool | None = None
    is_adjustment: bool | None = None
    adjustment_reason: str | None = Field(default=None, max_length=20000)

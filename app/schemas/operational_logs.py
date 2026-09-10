import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

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

    @field_validator("recorded_at")
    @classmethod
    def past_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value > datetime.now(UTC):
            raise ValueError("Choose a timestamp with timezone that is not in the future")
        return value


class MaintenanceCreate(Input):
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


class MaintenanceStatus(Input):
    status: Literal["IN_PROGRESS", "COMPLETED", "CANCELLED"]
    notes: str = Field(min_length=1, max_length=20000)


class ProjectNoteCreate(Input):
    record_type: Literal["NOTE", "COMMENT"] = "NOTE"
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)


class RetireAsset(Input):
    reason: str = Field(min_length=1, max_length=20000)

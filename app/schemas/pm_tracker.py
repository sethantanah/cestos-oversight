"""Contracts for the preventive maintenance tracker."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PMTrackerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    equipment: str = Field(min_length=1, max_length=300)
    service_type: str = Field(min_length=1, max_length=200)
    due_date: date
    planned_actual: str = Field("PLANNED", min_length=1, max_length=20)
    pm_completed: bool = False
    defects_found: str | None = Field(None, max_length=20000)
    parts_required: str | None = Field(None, max_length=10000)
    technician_employee_id: uuid.UUID | None = None
    technician_name: str | None = Field(None, max_length=200)
    remarks: str | None = Field(None, max_length=20000)

    @field_validator("planned_actual")
    @classmethod
    def normalize_plan_type(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"PLANNED", "ACTUAL"}:
            raise ValueError("Choose Planned or Actual")
        return normalized


class PMTrackerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    equipment: str | None = Field(None, min_length=1, max_length=300)
    service_type: str | None = Field(None, min_length=1, max_length=200)
    due_date: date | None = None
    planned_actual: str | None = Field(None, min_length=1, max_length=20)
    pm_completed: bool | None = None
    defects_found: str | None = Field(None, max_length=20000)
    parts_required: str | None = Field(None, max_length=10000)
    technician_employee_id: uuid.UUID | None = None
    technician_name: str | None = Field(None, max_length=200)
    remarks: str | None = Field(None, max_length=20000)


class PMTrackerRead(PMTrackerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None
    updated_by_id: uuid.UUID | None = None

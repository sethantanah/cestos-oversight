"""Contracts for the project equipment register."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EquipmentRegisterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    equipment: str = Field(min_length=1, max_length=300)
    unit_number: str | None = Field(None, max_length=100)
    equipment_type: str | None = Field(None, max_length=200)
    status: str = Field("Operational / Monitoring", min_length=1, max_length=100)
    open_defects: str | None = Field(None, max_length=20000)
    action_required: str | None = Field(None, max_length=20000)
    priority: str = Field("MEDIUM", min_length=1, max_length=30)
    remarks: str | None = Field(None, max_length=20000)


class EquipmentRegisterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    equipment: str | None = Field(None, min_length=1, max_length=300)
    unit_number: str | None = Field(None, max_length=100)
    equipment_type: str | None = Field(None, max_length=200)
    status: str | None = Field(None, min_length=1, max_length=100)
    open_defects: str | None = Field(None, max_length=20000)
    action_required: str | None = Field(None, max_length=20000)
    priority: str | None = Field(None, min_length=1, max_length=30)
    remarks: str | None = Field(None, max_length=20000)


class EquipmentRegisterRead(EquipmentRegisterCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None
    updated_by_id: uuid.UUID | None = None

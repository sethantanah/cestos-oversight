import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class BreakdownJobCardCreate(BaseModel):
    project_id: uuid.UUID | None = None
    site_location_id: uuid.UUID | None = None
    asset_id: uuid.UUID
    work_order_id: uuid.UUID | None = None
    job_control: dict[str, Any] = Field(default_factory=dict)
    reported_failure: str = ""
    corrective_action: str = ""
    parts_materials: list[dict[str, Any]] = Field(default_factory=list)
    labour_downtime: list[dict[str, Any]] = Field(default_factory=list)
    test_release: dict[str, Any] = Field(default_factory=dict)
    signatures: dict[str, Any] = Field(default_factory=dict)

class BreakdownJobCardRead(BreakdownJobCardCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_card_number: str
    status: str
    created_at: datetime
    updated_at: datetime

class BreakdownJobCardUpdate(BaseModel):
    status: Literal["DRAFT", "IN_PROGRESS", "COMPLETED", "CANCELLED"] | None = None
    site_location_id: uuid.UUID | None = None
    job_control: dict[str, Any] | None = None
    reported_failure: str | None = None
    corrective_action: str | None = None
    parts_materials: list[dict[str, Any]] | None = None
    labour_downtime: list[dict[str, Any]] | None = None
    test_release: dict[str, Any] | None = None
    signatures: dict[str, Any] | None = None

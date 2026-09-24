import uuid
from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class PMTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    equipment_type: str | None = None
    pm_interval: str = "250 Hours"
    inspection_items: list[dict[str, Any]] = Field(default_factory=list)

class PMTemplateRead(PMTemplateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID

class PMJobCardCreate(BaseModel):
    job_card_number: str | None = Field(default=None, min_length=1, max_length=50)
    project_id: uuid.UUID | None = None
    site_location_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    work_order_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    pm_control: dict[str, Any] = Field(default_factory=dict)
    inspection_items: list[dict[str, Any]] | None = None
    technicians: list[dict[str, Any]] = Field(default_factory=list)

class PMJobCardUpdate(BaseModel):
    job_card_number: str | None = Field(default=None, min_length=1, max_length=50)
    project_id: uuid.UUID | None = None
    site_location_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    status: Literal["DRAFT", "IN_PROGRESS", "PENDING_SIGNOFF", "COMPLETED", "CANCELLED"] | None = None
    pm_control: dict[str, Any] | None = None
    inspection_items: list[dict[str, Any]] | None = None
    service_defect_control: dict[str, Any] | None = None
    machine_release: dict[str, Any] | None = None
    technicians: list[dict[str, Any]] | None = None
    signatures: dict[str, Any] | None = None
    supervisor_comments: str | None = None
    work_order_id: uuid.UUID | None = None

class PMJobCardRead(PMJobCardCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_card_number: str
    work_order_id: uuid.UUID | None = None
    status: str
    service_defect_control: dict[str, Any]
    machine_release: dict[str, Any]
    signatures: dict[str, Any]
    supervisor_comments: str | None
    created_at: datetime
    updated_at: datetime

"""Contracts for operational action tracker records."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionTrackerBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: uuid.UUID | None = None
    action_date: date
    asset_id: uuid.UUID | None = None
    equipment_area: str = Field(min_length=1, max_length=300)
    issue_finding: str = Field(min_length=1, max_length=20000)
    action_taken: str | None = Field(None, max_length=20000)
    parts_required: str | None = Field(None, max_length=10000)
    responsible_employee_id: uuid.UUID | None = None
    responsible_name: str | None = Field(None, max_length=200)
    priority: str = Field("MEDIUM", min_length=1, max_length=30)
    status: str = Field("OPEN", min_length=1, max_length=30)
    completion_date: date | None = None
    remarks: str | None = Field(None, max_length=20000)

    @model_validator(mode="after")
    def normalize_values(self):
        self.priority = self.priority.upper()
        self.status = self.status.upper().replace(" ", "_")
        if self.completion_date and self.completion_date < self.action_date:
            raise ValueError("Completion date must be on or after the action date")
        return self


class ActionTrackerCreate(ActionTrackerBase):
    pass


class ActionTrackerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: uuid.UUID | None = None
    action_date: date | None = None
    asset_id: uuid.UUID | None = None
    equipment_area: str | None = Field(None, min_length=1, max_length=300)
    issue_finding: str | None = Field(None, min_length=1, max_length=20000)
    action_taken: str | None = Field(None, max_length=20000)
    parts_required: str | None = Field(None, max_length=10000)
    responsible_employee_id: uuid.UUID | None = None
    responsible_name: str | None = Field(None, max_length=200)
    priority: str | None = Field(None, min_length=1, max_length=30)
    status: str | None = Field(None, min_length=1, max_length=30)
    completion_date: date | None = None
    remarks: str | None = Field(None, max_length=20000)


class ActionTrackerRead(ActionTrackerBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None
    updated_by_id: uuid.UUID | None = None

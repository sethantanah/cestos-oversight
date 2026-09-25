"""Contracts for fleet maintenance assessment reports."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MaintenanceAssessmentBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_number: str | None = Field(None, min_length=1, max_length=50)
    project_id: uuid.UUID | None = None
    site_location_id: uuid.UUID | None = None
    project_name_custom: str | None = Field(None, max_length=200)
    reporting_period_start: date
    reporting_period_end: date
    report_date: date
    prepared_by_employee_id: uuid.UUID | None = None
    prepared_by_name: str = Field(min_length=1, max_length=200)
    prepared_by_position: str | None = Field(None, max_length=150)
    submitted_to: str | None = Field(None, max_length=200)
    status: str = Field("DRAFT", min_length=1, max_length=30)
    executive_summary: str | None = Field(None, max_length=20000)
    equipment_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    equipment_fleet: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    maintenance_assessment: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    preventive_improvements: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    spare_parts_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    manpower_requirements: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    control_documents: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    action_plan: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    maintenance_kpis: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    conclusion: str | None = Field(None, max_length=20000)

    @field_validator("report_number", mode="before")
    @classmethod
    def normalize_report_number(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_period(self):
        if self.reporting_period_end < self.reporting_period_start:
            raise ValueError("Reporting period end must be on or after its start")
        return self


class MaintenanceAssessmentCreate(MaintenanceAssessmentBase):
    pass


class MaintenanceAssessmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_number: str | None = Field(None, min_length=1, max_length=50)
    project_id: uuid.UUID | None = None
    site_location_id: uuid.UUID | None = None
    project_name_custom: str | None = Field(None, max_length=200)
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    report_date: date | None = None
    prepared_by_employee_id: uuid.UUID | None = None
    prepared_by_name: str | None = Field(None, min_length=1, max_length=200)
    prepared_by_position: str | None = Field(None, max_length=150)
    submitted_to: str | None = Field(None, max_length=200)
    status: str | None = Field(None, min_length=1, max_length=30)
    executive_summary: str | None = Field(None, max_length=20000)
    equipment_asset_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    equipment_fleet: list[dict[str, Any]] | None = Field(None, max_length=200)
    maintenance_assessment: list[dict[str, Any]] | None = Field(None, max_length=500)
    preventive_improvements: list[dict[str, Any]] | None = Field(None, max_length=200)
    spare_parts_actions: list[dict[str, Any]] | None = Field(None, max_length=200)
    manpower_requirements: list[dict[str, Any]] | None = Field(None, max_length=100)
    control_documents: list[dict[str, Any]] | None = Field(None, max_length=200)
    action_plan: list[dict[str, Any]] | None = Field(None, max_length=300)
    maintenance_kpis: list[dict[str, Any]] | None = Field(None, max_length=200)
    conclusion: str | None = Field(None, max_length=20000)

    @field_validator("report_number", mode="before")
    @classmethod
    def normalize_report_number(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class MaintenanceAssessmentRead(MaintenanceAssessmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    report_number: str
    created_at: datetime
    updated_at: datetime
    created_by_id: uuid.UUID | None = None
    updated_by_id: uuid.UUID | None = None

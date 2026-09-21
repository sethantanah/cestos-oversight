import uuid
from datetime import date as py_date, datetime
from decimal import Decimal

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.drilling import (
    DrillHoleStatus,
    DrillingProgramStatus,
    ShiftReportStatus,
    ShiftType,
    TimeCategory,
)


# --- Drilling Program Schemas ---
class DrillingProgramCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    code: str | None = Field(None, max_length=50)
    target_metres: Decimal | None = Field(None, ge=0)
    start_date: py_date | None = None
    end_date: py_date | None = None
    description: str | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_name_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" not in data and "program_name" in data:
                data["name"] = data["program_name"]
        return data


class DrillingProgramUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, max_length=50)
    target_metres: Decimal | None = Field(None, ge=0)
    status: DrillingProgramStatus | None = None
    start_date: py_date | None = None
    end_date: py_date | None = None
    description: str | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_name_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" not in data and "program_name" in data:
                data["name"] = data["program_name"]
        return data


class DrillingProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    code: str | None = None
    target_metres: float | None = None
    drilled_metres: float | None = 0.0
    status: DrillingProgramStatus
    start_date: py_date | None = None
    end_date: py_date | None = None
    description: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Drill Hole Schemas ---
class DrillHoleCreate(BaseModel):
    project_id: uuid.UUID
    program_id: uuid.UUID | None = None
    hole_number: str = Field(..., min_length=1, max_length=100)
    drilling_method: str | None = Field(None, max_length=100)
    target_depth_m: Decimal | None = Field(None, ge=0)
    azimuth_deg: Decimal | None = Field(None, ge=0, le=360)
    dip_deg: Decimal | None = Field(None, ge=-90, le=90)
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_method_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "drilling_method" not in data and "drilling_type" in data:
                data["drilling_method"] = data["drilling_type"]
        return data


class DrillHoleUpdate(BaseModel):
    hole_number: str | None = Field(None, min_length=1, max_length=100)
    program_id: uuid.UUID | None = None
    drilling_method: str | None = Field(None, max_length=100)
    target_depth_m: Decimal | None = Field(None, ge=0)
    final_depth_m: Decimal | None = Field(None, ge=0)
    azimuth_deg: Decimal | None = Field(None, ge=0, le=360)
    dip_deg: Decimal | None = Field(None, ge=-90, le=90)
    status: DrillHoleStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None


class DrillHoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    program_id: uuid.UUID | None = None
    hole_number: str
    drilling_method: str | None = None
    target_depth_m: float | None = None
    final_depth_m: float | None = None
    azimuth_deg: float | None = None
    dip_deg: float | None = None
    status: DrillHoleStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Shift Sub-item Schemas ---
class DrillingShiftIntervalCreate(BaseModel):
    drill_hole_id: uuid.UUID
    from_depth_m: Decimal = Field(..., ge=0)
    to_depth_m: Decimal = Field(..., ge=0)
    core_recovered_m: Decimal | None = Field(None, ge=0)
    drilling_method: str | None = Field(None, max_length=50)
    ground_conditions: str | None = Field(None, max_length=200)


class DrillingShiftIntervalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shift_report_id: uuid.UUID
    drill_hole_id: uuid.UUID
    from_depth_m: float
    to_depth_m: float
    drilled_metres: float
    core_recovered_m: float | None = None
    core_recovery_pct: float | None = None
    drilling_method: str | None = None
    ground_conditions: str | None = None


class DrillingShiftTimeSegmentCreate(BaseModel):
    category: TimeCategory
    reason_code: str = Field(..., min_length=1, max_length=100)
    hours: Decimal = Field(..., gt=0, le=24)
    comments: str | None = None


class DrillingShiftTimeSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shift_report_id: uuid.UUID
    category: TimeCategory
    reason_code: str
    hours: float
    comments: str | None = None


class DrillingShiftCrewCreate(BaseModel):
    employee_id: uuid.UUID
    role_on_shift: str = Field(..., min_length=1, max_length=100)
    hours_worked: Decimal = Field(Decimal("12.0"), gt=0, le=24)


class DrillingShiftCrewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shift_report_id: uuid.UUID
    employee_id: uuid.UUID
    role_on_shift: str
    hours_worked: float


# --- Drilling Shift Report Schemas ---
class DrillingShiftReportCreate(BaseModel):
    project_id: uuid.UUID
    rig_id: uuid.UUID
    program_id: uuid.UUID | None = None
    date: py_date
    shift_type: ShiftType = ShiftType.DAY
    supervisor_id: uuid.UUID | None = None
    status: ShiftReportStatus | None = None
    notes: str | None = None
    intervals: list[DrillingShiftIntervalCreate] = Field(default_factory=list)
    time_segments: list[DrillingShiftTimeSegmentCreate] = Field(default_factory=list)
    crew_members: list[DrillingShiftCrewCreate] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def populate_date_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "date" not in data and "shift_date" in data:
                data["date"] = data["shift_date"]
        return data


class DrillingShiftReportUpdate(BaseModel):
    project_id: uuid.UUID | None = None
    rig_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    date: py_date | None = None
    shift_type: ShiftType | None = None
    supervisor_id: uuid.UUID | None = None
    notes: str | None = None
    correction_reason: str | None = None
    total_metres: Decimal | None = None
    total_metres_drilled: Decimal | None = None
    avg_core_recovery_pct: Decimal | None = None
    core_recovery_pct: Decimal | None = None
    total_productive_hours: Decimal | None = None
    productive_hours: Decimal | None = None
    total_nonproductive_hours: Decimal | None = None
    intervals: list[DrillingShiftIntervalCreate] | None = None
    time_segments: list[DrillingShiftTimeSegmentCreate] | None = None
    crew_members: list[DrillingShiftCrewCreate] | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_date_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "date" not in data and "shift_date" in data:
                data["date"] = data["shift_date"]
            if "total_metres" not in data and "total_metres_drilled" in data:
                data["total_metres"] = data["total_metres_drilled"]
            if "avg_core_recovery_pct" not in data and "core_recovery_pct" in data:
                data["avg_core_recovery_pct"] = data["core_recovery_pct"]
            if "total_productive_hours" not in data and "productive_hours" in data:
                data["total_productive_hours"] = data["productive_hours"]
        return data


class DrillingShiftReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    report_number: str
    project_id: uuid.UUID
    rig_id: uuid.UUID
    program_id: uuid.UUID | None = None
    date: py_date
    shift_type: ShiftType
    supervisor_id: uuid.UUID | None = None
    status: ShiftReportStatus
    submitted_at: datetime | None = None
    submitted_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    approved_by_id: uuid.UUID | None = None
    return_reason: str | None = None
    correction_reason: str | None = None
    total_metres: float
    total_productive_hours: float
    total_nonproductive_hours: float
    avg_core_recovery_pct: float | None = None
    notes: str | None = None
    supervisor_name: str | None = None
    supervisor_role: str | None = None
    submitted_by_name: str | None = None
    submitted_by_role: str | None = None
    approved_by_name: str | None = None
    approved_by_role: str | None = None
    project_name: str | None = None
    program_name: str | None = None
    rig_name: str | None = None
    intervals: list[DrillingShiftIntervalResponse] = Field(default_factory=list)
    time_segments: list[DrillingShiftTimeSegmentResponse] = Field(default_factory=list)
    crew_members: list[DrillingShiftCrewResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# --- Action Request Schemas ---
class SubmitShiftReportRequest(BaseModel):
    notes: str | None = None


class ApproveShiftReportRequest(BaseModel):
    notes: str | None = None


class ReturnShiftReportRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Reason for returning the shift report for revision")


# --- Summary & Analytics Schemas ---
class ProjectDrillingSummaryResponse(BaseModel):
    project_id: uuid.UUID
    total_programs: int
    total_holes: int
    active_holes: int
    completed_holes: int
    total_shifts_submitted: int
    total_shifts_approved: int
    total_metres_drilled: float
    total_productive_hours: float
    total_standby_hours: float
    total_maintenance_hours: float
    overall_avg_core_recovery_pct: float | None = None

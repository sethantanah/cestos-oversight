import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.maintenance_hse import (
    FailureTaxonomy,
    HseActionStatus,
    HseIncidentStatus,
    HseIncidentType,
    HseSeverity,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)


# --- Work Order Cost Lines ---
class WorkOrderCostLineCreate(BaseModel):
    cost_type: str = Field(..., min_length=1, max_length=30)  # PARTS, LABOUR, SUBCONTRACTOR
    description: str = Field(..., min_length=1, max_length=255)
    part_number: str | None = Field(None, max_length=100)
    quantity: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)


class WorkOrderCostLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_order_id: uuid.UUID
    cost_type: str
    description: str
    part_number: str | None = None
    quantity: float
    unit_cost: float
    total_cost: float
    currency: str
    posted_to_subledger: bool


# --- Work Orders ---
class MaintenanceWorkOrderCreate(BaseModel):
    asset_id: uuid.UUID
    project_id: uuid.UUID | None = None
    defect_id: uuid.UUID | None = None
    inspection_id: uuid.UUID | None = None
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    work_type: WorkOrderType = WorkOrderType.CORRECTIVE
    priority: WorkOrderPriority = WorkOrderPriority.MEDIUM
    failure_taxonomy: FailureTaxonomy | None = None
    assigned_technician_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    meter_reading: Decimal | None = Field(None, ge=0)
    notes: str | None = None
    cost_lines: list[WorkOrderCostLineCreate] = Field(default_factory=list)


class MaintenanceWorkOrderUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    work_type: WorkOrderType | None = None
    priority: WorkOrderPriority | None = None
    status: WorkOrderStatus | None = None
    failure_taxonomy: FailureTaxonomy | None = None
    root_cause: str | None = None
    remedy: str | None = None
    downtime_hours: Decimal | None = Field(None, ge=0)
    estimated_lost_contribution: Decimal | None = Field(None, ge=0)
    assigned_technician_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = None


class MaintenanceWorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    wo_number: str
    asset_id: uuid.UUID
    project_id: uuid.UUID | None = None
    defect_id: uuid.UUID | None = None
    inspection_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    work_type: WorkOrderType
    priority: WorkOrderPriority
    status: WorkOrderStatus
    failure_taxonomy: FailureTaxonomy | None = None
    root_cause: str | None = None
    remedy: str | None = None
    downtime_hours: float
    estimated_lost_contribution: float
    total_parts_cost: float = 0.0
    total_labour_cost: float = 0.0
    total_cost: float = 0.0
    assigned_technician_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by_id: uuid.UUID | None = None
    meter_reading: float | None = None
    notes: str | None = None
    cost_lines: list[WorkOrderCostLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CompleteWorkOrderRequest(BaseModel):
    root_cause: str | None = None
    remedy: str | None = None
    downtime_hours: Decimal = Field(Decimal("0.0"), ge=0)
    estimated_lost_contribution: Decimal = Field(Decimal("0.0"), ge=0)
    notes: str | None = None


# --- Reliability & Asset Performance ---
class AssetReliabilitySummaryResponse(BaseModel):
    asset_id: uuid.UUID
    asset_name: str
    total_work_orders: int
    open_work_orders: int
    completed_work_orders: int
    total_downtime_hours: float
    availability_pct: float
    total_maintenance_cost: float
    maintenance_cost_per_hour: float
    mtbf_hours: float | None = None
    mttr_hours: float | None = None
    failure_count_by_taxonomy: dict[str, int]


# --- HSE Corrective Actions ---
class HseCorrectiveActionCreate(BaseModel):
    description: str = Field(..., min_length=1)
    assigned_to_id: uuid.UUID
    due_date: date


class HseCorrectiveActionUpdate(BaseModel):
    description: str | None = Field(None, min_length=1)
    assigned_to_id: uuid.UUID | None = None
    due_date: date | None = None
    status: HseActionStatus | None = None
    closure_notes: str | None = None


class HseCorrectiveActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    action_number: str
    incident_id: uuid.UUID
    description: str
    assigned_to_id: uuid.UUID
    due_date: date
    status: HseActionStatus
    closure_notes: str | None = None
    closed_at: datetime | None = None
    closed_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


# --- HSE Incidents ---
class HseIncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    incident_type: HseIncidentType
    severity: HseSeverity = HseSeverity.MEDIUM
    occurred_at: datetime
    project_id: uuid.UUID
    site_location_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    reported_by_id: uuid.UUID
    description: str = Field(..., min_length=1)
    immediate_actions_taken: str | None = None
    root_cause_analysis: str | None = None
    notes: str | None = None
    actions: list[HseCorrectiveActionCreate] = Field(default_factory=list)


class HseIncidentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    incident_type: HseIncidentType | None = None
    severity: HseSeverity | None = None
    status: HseIncidentStatus | None = None
    description: str | None = None
    immediate_actions_taken: str | None = None
    root_cause_analysis: str | None = None
    notes: str | None = None


class HseIncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    incident_number: str
    title: str
    incident_type: HseIncidentType
    severity: HseSeverity
    status: HseIncidentStatus
    occurred_at: datetime
    project_id: uuid.UUID
    site_location_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    reported_by_id: uuid.UUID
    description: str
    immediate_actions_taken: str | None = None
    root_cause_analysis: str | None = None
    notes: str | None = None
    actions: list[HseCorrectiveActionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

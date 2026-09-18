import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.control_tower import ClientArtifactType, TenderStage


# --- CEO Control Tower Summary ---
class CeoControlTowerSummaryResponse(BaseModel):
    company_name: str
    total_projects: int
    active_rigs: int
    total_revenue: float
    total_direct_cost: float
    net_contribution: float
    contribution_margin_pct: float
    total_metres_drilled: float
    avg_asset_availability_pct: float
    active_work_orders: int
    open_hse_incidents: int
    project_summaries: list[dict]


# --- Supervisor Scorecard Schemas ---
class SupervisorScorecardCreate(BaseModel):
    supervisor_id: uuid.UUID
    project_id: uuid.UUID | None = None
    period_start: date
    period_end: date
    production_score: Decimal = Field(Decimal("0.0"), ge=0, le=25)
    rig_condition_score: Decimal = Field(Decimal("0.0"), ge=0, le=20)
    downtime_score: Decimal = Field(Decimal("0.0"), ge=0, le=15)
    hse_score: Decimal = Field(Decimal("0.0"), ge=0, le=15)
    consumables_score: Decimal = Field(Decimal("0.0"), ge=0, le=10)
    crew_management_score: Decimal = Field(Decimal("0.0"), ge=0, le=5)
    reporting_score: Decimal = Field(Decimal("0.0"), ge=0, le=5)
    stewardship_score: Decimal = Field(Decimal("0.0"), ge=0, le=5)
    notes: str | None = None


class SupervisorScorecardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    scorecard_number: str
    supervisor_id: uuid.UUID
    project_id: uuid.UUID | None = None
    period_start: date
    period_end: date
    production_score: float
    rig_condition_score: float
    downtime_score: float
    hse_score: float
    consumables_score: float
    crew_management_score: float
    reporting_score: float
    stewardship_score: float
    overall_weighted_score: float
    grade: str
    notes: str | None = None
    created_at: datetime


# --- Commercial Opportunity Schemas ---
class CommercialOpportunityCreate(BaseModel):
    client_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=200)
    tender_stage: TenderStage = TenderStage.PROSPECT
    win_probability_pct: Decimal = Field(Decimal("50.0"), ge=0, le=100)
    estimated_value: Decimal = Field(Decimal("0.0"), ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    expected_close_date: date | None = None
    notes: str | None = None


class CommercialOpportunityUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    tender_stage: TenderStage | None = None
    win_probability_pct: Decimal | None = Field(None, ge=0, le=100)
    estimated_value: Decimal | None = Field(None, ge=0)
    expected_close_date: date | None = None
    notes: str | None = None


class CommercialOpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    opportunity_number: str
    client_id: uuid.UUID
    title: str
    tender_stage: TenderStage
    win_probability_pct: float
    estimated_value: float
    currency: str
    expected_close_date: date | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Client Grants & Published Artifacts ---
class ClientProjectGrantCreate(BaseModel):
    client_id: uuid.UUID
    project_id: uuid.UUID


class ClientProjectGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    client_id: uuid.UUID
    project_id: uuid.UUID
    granted_at: datetime


class PublishArtifactRequest(BaseModel):
    client_id: uuid.UUID
    project_id: uuid.UUID
    artifact_type: ClientArtifactType
    entity_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class ClientPublishedArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    client_id: uuid.UUID
    project_id: uuid.UUID
    artifact_type: ClientArtifactType
    entity_id: uuid.UUID
    title: str
    description: str | None = None
    published_at: datetime


class ClientPortalOverviewResponse(BaseModel):
    client_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    total_published_artifacts: int
    published_artifacts: list[ClientPublishedArtifactResponse]

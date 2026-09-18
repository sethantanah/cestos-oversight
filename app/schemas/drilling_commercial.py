import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.drilling_commercial import (
    ContractStatus,
    CostCategory,
    RateType,
    RevenueCategory,
)


# --- Rate Card Schemas ---
class ContractRateCardCreate(BaseModel):
    rate_type: RateType
    drilling_method: str | None = Field(None, max_length=100)
    depth_from_m: Decimal | None = Field(None, ge=0)
    depth_to_m: Decimal | None = Field(None, ge=0)
    unit_rate: Decimal = Field(..., ge=0)
    description: str | None = Field(None, max_length=255)


class ContractRateCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    rate_type: RateType
    drilling_method: str | None = None
    depth_from_m: float | None = None
    depth_to_m: float | None = None
    unit_rate: float
    description: str | None = None


# --- Project Contract Schemas ---
class ContractAttachment(BaseModel):
    name: str
    url: str


class ProjectContractCreate(BaseModel):
    project_id: uuid.UUID
    contract_number: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)
    currency: str = Field("USD", min_length=3, max_length=3)
    start_date: date
    end_date: date | None = None
    status: ContractStatus = ContractStatus.ACTIVE
    notes: str | None = None
    attachments: list[ContractAttachment] = Field(default_factory=list)
    rate_cards: list[ContractRateCardCreate] = Field(default_factory=list)


class ProjectContractUpdate(BaseModel):
    contract_number: str | None = Field(None, min_length=1, max_length=100)
    title: str | None = Field(None, min_length=1, max_length=200)
    currency: str | None = Field(None, min_length=3, max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    status: ContractStatus | None = None
    notes: str | None = None
    attachments: list[ContractAttachment] | None = None
    rate_cards: list[ContractRateCardCreate] | None = None


class ProjectContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    contract_number: str
    title: str
    currency: str
    start_date: date
    end_date: date | None = None
    status: ContractStatus
    notes: str | None = None
    attachments: list[ContractAttachment] = Field(default_factory=list)
    rate_cards: list[ContractRateCardResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# --- Cost Subledger Schemas ---
class CostSubledgerEntryCreate(BaseModel):
    project_id: uuid.UUID
    rig_id: uuid.UUID | None = None
    shift_report_id: uuid.UUID | None = None
    cost_category: CostCategory
    description: str = Field(..., min_length=1, max_length=255)
    quantity: Decimal = Field(..., gt=0)
    unit_of_measure: str = Field(..., min_length=1, max_length=30)
    unit_cost: Decimal = Field(..., ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    exchange_rate_to_base: Decimal = Field(Decimal("1.000000"), gt=0)
    source_entity_type: str | None = Field(None, max_length=50)
    source_entity_id: uuid.UUID | None = None
    notes: str | None = None


class CostSubledgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    rig_id: uuid.UUID | None = None
    shift_report_id: uuid.UUID | None = None
    cost_category: CostCategory
    description: str
    quantity: float
    unit_of_measure: str
    unit_cost: float
    total_cost: float
    currency: str
    exchange_rate_to_base: float
    total_cost_base: float
    source_entity_type: str | None = None
    source_entity_id: uuid.UUID | None = None
    posted_at: datetime


# --- Revenue Subledger Schemas ---
class RevenueSubledgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    rig_id: uuid.UUID | None = None
    shift_report_id: uuid.UUID | None = None
    contract_id: uuid.UUID | None = None
    rate_card_id: uuid.UUID | None = None
    revenue_category: RevenueCategory
    description: str
    quantity: float
    unit_rate: float
    total_revenue: float
    currency: str
    exchange_rate_to_base: float
    total_revenue_base: float
    posted_at: datetime


# --- Financial & Performance Summaries ---
class ProjectFinancialSummaryResponse(BaseModel):
    project_id: uuid.UUID
    currency: str = "USD"
    total_revenue: float
    total_direct_cost: float
    cost_breakdown_by_category: dict[str, float]
    net_contribution: float
    contribution_margin_pct: float
    total_metres_drilled: float
    revenue_per_metre: float
    cost_per_metre: float
    total_fuel_litres: float
    litres_per_metre: float
    target_variance: float


class RigPerformanceSummaryResponse(BaseModel):
    rig_id: uuid.UUID
    rig_name: str
    currency: str = "USD"
    total_shifts: int
    total_metres_drilled: float
    total_revenue: float
    total_direct_cost: float
    net_contribution: float
    contribution_margin_pct: float
    cost_per_metre: float
    productive_hours: float
    nonproductive_hours: float

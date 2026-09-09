import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.project import ProjectStatus
from app.schemas.asset import AssetAssignmentRead
from app.schemas.client import ClientRead
from app.schemas.common import ORMModel
from app.schemas.employee import EmployeeAssignmentRead, EmployeeRead
from app.schemas.location import LocationRead


class ProjectCreate(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    project_type: str | None = Field(default=None, max_length=100)
    drilling_type: str | None = Field(default=None, max_length=100)
    contract_number: str | None = Field(default=None, max_length=100)
    project_manager_id: uuid.UUID | None = None
    start_date: date | None = None
    expected_end_date: date | None = None
    actual_end_date: date | None = None
    status: ProjectStatus = ProjectStatus.PLANNING
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    target_metres: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    default_currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: str | None = None


class ProjectUpdate(BaseModel):
    client_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    project_type: str | None = Field(default=None, max_length=100)
    drilling_type: str | None = Field(default=None, max_length=100)
    contract_number: str | None = Field(default=None, max_length=100)
    project_manager_id: uuid.UUID | None = None
    start_date: date | None = None
    expected_end_date: date | None = None
    actual_end_date: date | None = None
    status: ProjectStatus | None = None
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    target_metres: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None
    is_active: bool | None = None


class ProjectRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_number: str
    client_id: uuid.UUID
    name: str
    description: str | None
    project_type: str | None
    drilling_type: str | None
    contract_number: str | None
    project_manager_id: uuid.UUID | None
    start_date: date | None
    expected_end_date: date | None
    actual_end_date: date | None
    status: ProjectStatus
    contract_value: Decimal | None
    target_metres: Decimal | None
    default_currency: str
    notes: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


ProjectListItem = ProjectRead


class ProjectOverview(ORMModel):
    project: ProjectRead
    client: ClientRead | None
    project_manager: EmployeeRead | None
    sites: list[LocationRead]
    employee_count: int
    asset_count: int
    current_employees: list[EmployeeRead]
    current_assets: list["AssetRead"]
    recent_employee_assignments: list[EmployeeAssignmentRead]
    recent_asset_assignments: list[AssetAssignmentRead]


from app.schemas.asset import AssetRead  # noqa: E402  (circular-safe: runtime only)

ProjectOverview.model_rebuild()

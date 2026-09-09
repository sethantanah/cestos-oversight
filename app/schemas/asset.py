import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.asset import AssetDocumentType as DocumentType
from app.models.asset import (
    AssetStatus,
    ComponentStatus,
    MeterType,
    OwnershipType,
    ReadingType,
)
from app.models.employee import AssignmentStatus
from app.schemas.common import ORMModel
from app.schemas.employee import EmployeeRead
from app.schemas.location import LocationRead


class CategoryFields(BaseModel):
    code: str | None = Field(default=None, max_length=30)
    default_meter_type: MeterType | None = None
    is_mobile: bool = True
    requires_registration: bool = False
    requires_insurance: bool = False
    requires_operator: bool = False


class AssetFields(BaseModel):
    engine_manufacturer: str | None = Field(default=None, max_length=150)
    engine_model: str | None = Field(default=None, max_length=150)
    chassis_number: str | None = Field(default=None, max_length=150)
    vin: str | None = Field(default=None, max_length=150)
    ownership_entity: str | None = Field(default=None, max_length=200)
    purchase_currency: str | None = Field(default=None, max_length=10)
    commission_date: date | None = None
    supplier_id: uuid.UUID | None = None
    warranty_start_date: date | None = None
    expected_service_life_years: Decimal | None = Field(default=None, ge=0)
    residual_value: Decimal | None = Field(default=None, ge=0)
    primary_operator_id: uuid.UUID | None = None
    profile_photo_url: str | None = None
    qr_code_value: str | None = Field(default=None, max_length=255)
    barcode_value: str | None = Field(default=None, max_length=255)


class ComponentFields(BaseModel):
    parent_component_id: uuid.UUID | None = None
    component_number: str | None = Field(default=None, max_length=50)
    part_number: str | None = Field(default=None, max_length=150)
    expected_life_cycles: Decimal | None = Field(default=None, ge=0)
    removal_date: date | None = None
    is_active: bool = True


class AssignmentFields(BaseModel):
    primary_operator_id: uuid.UUID | None = None
    expected_return_at: datetime | None = None
    assignment_reason: str | None = Field(default=None, max_length=200)


class AssetCategoryCreate(CategoryFields):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    parent_category_id: uuid.UUID | None = None


class AssetCategoryRead(CategoryFields, ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    parent_category_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AssetCreate(AssetFields):
    category_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    manufacturer: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=150)
    serial_number: str | None = Field(default=None, max_length=150)
    year_of_manufacture: int | None = Field(default=None, ge=1950, le=2100)
    purchase_date: date | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    ownership_type: OwnershipType = OwnershipType.OWNED
    engine_number: str | None = Field(default=None, max_length=150)
    registration_number: str | None = Field(default=None, max_length=100)
    meter_type: MeterType = MeterType.NONE
    current_meter_reading: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    status: AssetStatus = AssetStatus.AVAILABLE
    default_location_id: uuid.UUID | None = None
    responsible_employee_id: uuid.UUID | None = None
    photo_url: str | None = Field(default=None, max_length=1024)
    warranty_expiry_date: date | None = None
    insurance_expiry_date: date | None = None
    notes: str | None = None


class AssetUpdate(AssetFields):
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    manufacturer: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=150)
    serial_number: str | None = Field(default=None, max_length=150)
    year_of_manufacture: int | None = Field(default=None, ge=1950, le=2100)
    purchase_date: date | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    ownership_type: OwnershipType | None = None
    engine_number: str | None = Field(default=None, max_length=150)
    registration_number: str | None = Field(default=None, max_length=100)
    meter_type: MeterType | None = None
    current_meter_reading: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    status: AssetStatus | None = None
    default_location_id: uuid.UUID | None = None
    responsible_employee_id: uuid.UUID | None = None
    photo_url: str | None = Field(default=None, max_length=1024)
    warranty_expiry_date: date | None = None
    insurance_expiry_date: date | None = None
    notes: str | None = None
    is_active: bool | None = None


class AssetRead(AssetFields, ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_number: str
    category_id: uuid.UUID
    name: str
    description: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    year_of_manufacture: int | None
    purchase_date: date | None
    purchase_price: Decimal | None
    ownership_type: OwnershipType
    engine_number: str | None
    registration_number: str | None
    meter_type: MeterType
    current_meter_reading: Decimal | None
    status: AssetStatus
    default_location_id: uuid.UUID | None
    responsible_employee_id: uuid.UUID | None
    photo_url: str | None
    warranty_expiry_date: date | None
    insurance_expiry_date: date | None
    notes: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


AssetListItem = AssetRead


class AssetComponentCreate(ComponentFields):
    name: str = Field(min_length=1, max_length=200)
    component_type: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=150)
    serial_number: str | None = Field(default=None, max_length=150)
    installation_date: date | None = None
    meter_at_installation: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    expected_life_hours: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    status: ComponentStatus = ComponentStatus.INSTALLED
    notes: str | None = None


class AssetComponentRead(ComponentFields, ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    name: str
    component_type: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    installation_date: date | None
    meter_at_installation: Decimal | None
    expected_life_hours: Decimal | None
    status: ComponentStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AssetAssignmentCreate(AssignmentFields):
    project_id: uuid.UUID
    location_id: uuid.UUID | None = None
    responsible_employee_id: uuid.UUID | None = None
    assigned_at: datetime
    starting_meter: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    notes: str | None = None


class AssetAssignmentUpdate(AssignmentFields):
    location_id: uuid.UUID | None = None
    responsible_employee_id: uuid.UUID | None = None
    returned_at: datetime | None = None
    ending_meter: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    status: AssignmentStatus | None = None
    notes: str | None = None


class AssetAssignmentRead(AssignmentFields, ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    assignment_number: str
    asset_id: uuid.UUID
    project_id: uuid.UUID
    location_id: uuid.UUID | None
    responsible_employee_id: uuid.UUID | None
    assigned_at: datetime
    returned_at: datetime | None
    starting_meter: Decimal | None
    ending_meter: Decimal | None
    status: AssignmentStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AssetMeterReadingCreate(BaseModel):
    reading: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    recorded_at: datetime
    reading_type: ReadingType
    source: str | None = Field(default=None, max_length=50)
    project_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    notes: str | None = None
    is_correction: bool = False
    is_adjustment: bool = False
    adjustment_reason: str | None = None
    evidence_photo_url: str | None = None


class AssetMeterReadingRead(ORMModel):
    is_adjustment: bool = False
    adjustment_reason: str | None = None
    previous_reading: Decimal | None = None
    meter_replaced: bool = False
    evidence_photo_url: str | None = None
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    reading: Decimal
    recorded_at: datetime
    reading_type: ReadingType
    source: str | None
    project_id: uuid.UUID | None
    location_id: uuid.UUID | None
    recorded_by_id: uuid.UUID | None
    notes: str | None
    created_at: datetime


class AssetDocumentCreate(BaseModel):
    document_type: DocumentType = DocumentType.OTHER
    title: str = Field(min_length=1, max_length=200)
    document_number: str | None = Field(default=None, max_length=100)
    file_url: str = Field(min_length=1, max_length=1024)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    issuing_authority: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class AssetDocumentRead(ORMModel):
    file_size: int | None = None
    verification_status: str = "PENDING"
    verified_at: datetime | None = None
    verified_by_id: uuid.UUID | None = None
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    document_type: DocumentType
    title: str
    document_number: str | None
    file_url: str
    file_name: str | None
    mime_type: str | None
    issue_date: date | None
    expiry_date: date | None
    issuing_authority: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AssetOverview(ORMModel):
    asset: AssetRead
    category: AssetCategoryRead | None
    current_assignment: AssetAssignmentRead | None
    current_location: LocationRead | None
    responsible_employee: EmployeeRead | None
    latest_meter_reading: AssetMeterReadingRead | None
    recent_assignments: list[AssetAssignmentRead]
    components: list[AssetComponentRead]
    documents: list[AssetDocumentRead]


# ---- location history ----


class AssetLocationHistoryCreate(BaseModel):
    location_id: uuid.UUID
    event_type: str
    project_id: uuid.UUID | None = None
    meter_reading: Decimal | None = None
    notes: str | None = None


class AssetLocationHistoryRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    location_id: uuid.UUID
    project_id: uuid.UUID | None
    event_type: str
    recorded_at: datetime
    meter_reading: Decimal | None
    recorded_by_id: uuid.UUID
    source_reference_type: str | None
    source_reference_id: uuid.UUID | None
    notes: str | None


# ---- status history ----


class AssetStatusHistoryRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    previous_status: str
    new_status: str
    changed_at: datetime
    changed_by_id: uuid.UUID
    reason: str | None
    project_id: uuid.UUID | None
    location_id: uuid.UUID | None
    source_reference: str | None


# ---- insurance ----


class AssetInsuranceCreate(BaseModel):
    provider: str
    policy_number: str
    coverage_type: str | None = None
    coverage_amount: Decimal | None = None
    currency: str | None = None
    start_date: date
    expiry_date: date
    premium_amount: Decimal | None = None
    notes: str | None = None


class AssetInsuranceUpdate(BaseModel):
    provider: str | None = None
    policy_number: str | None = None
    coverage_type: str | None = None
    coverage_amount: Decimal | None = None
    currency: str | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    premium_amount: Decimal | None = None
    status: str | None = None
    notes: str | None = None


class AssetInsuranceRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    provider: str
    policy_number: str
    coverage_type: str | None
    coverage_amount: Decimal | None
    currency: str | None
    start_date: date
    expiry_date: date
    premium_amount: Decimal | None
    status: str
    document_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---- registration ----


class AssetRegistrationCreate(BaseModel):
    registration_type: str
    registration_number: str
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class AssetRegistrationUpdate(BaseModel):
    registration_type: str | None = None
    registration_number: str | None = None
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: str | None = None
    notes: str | None = None


class AssetRegistrationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    registration_type: str
    registration_number: str
    issuing_authority: str | None
    issue_date: date | None
    expiry_date: date | None
    status: str
    document_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---- media ----


class AssetMediaCreate(BaseModel):
    media_type: str  # photo, video, document
    file_url: str
    caption: str | None = None
    is_primary: bool = False


class AssetMediaRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    media_type: str
    file_url: str
    storage_path: str | None
    file_name: str | None
    caption: str | None
    is_primary: bool
    is_active: bool
    captured_at: datetime | None
    uploaded_by_id: uuid.UUID
    created_at: datetime


# ---- inspections ----


class AssetInspectionCreate(BaseModel):
    inspection_type: str
    condition_status: str
    project_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    meter_reading: Decimal | None = None
    summary: str | None = None
    defects_found: bool = False
    defect_notes: str | None = None
    follow_up_required: bool = False


class AssetInspectionUpdate(BaseModel):
    condition_status: str | None = None
    summary: str | None = None
    defects_found: bool | None = None
    defect_notes: str | None = None
    follow_up_required: bool | None = None


class AssetInspectionRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    inspection_type: str
    inspection_date: datetime
    project_id: uuid.UUID | None
    location_id: uuid.UUID | None
    inspected_by_id: uuid.UUID
    meter_reading: Decimal | None
    condition_status: str
    summary: str | None
    defects_found: bool
    defect_notes: str | None
    follow_up_required: bool
    document_id: uuid.UUID | None
    created_at: datetime


# ---- defects ----


class AssetDefectCreate(BaseModel):
    severity: str  # low, medium, high, critical
    description: str
    inspection_id: uuid.UUID | None = None
    notes: str | None = None


class AssetDefectUpdate(BaseModel):
    severity: str | None = None
    description: str | None = None
    status: str | None = None
    notes: str | None = None


class AssetDefectRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    inspection_id: uuid.UUID | None
    reported_at: datetime
    reported_by_id: uuid.UUID
    severity: str
    description: str
    status: str
    resolved_at: datetime | None
    notes: str | None
    created_at: datetime


# ---- ownership history ----


class AssetOwnershipHistoryRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    asset_id: uuid.UUID
    ownership_type: str
    owner_or_provider: str
    start_date: date
    end_date: date | None
    purchase_or_contract_reference: str | None
    amount: Decimal | None
    currency: str | None
    notes: str | None
    created_at: datetime

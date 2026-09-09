"""Equipment actions and normalized related-record inputs."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.asset import AssetDocumentType as DocumentType
from app.models.asset import AssetStatus, ComponentStatus, MeterType, OwnershipType
from app.schemas.asset import (
    AssetAssignmentCreate,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusChange(Input):
    new_status: AssetStatus
    reason: str = Field(min_length=1)


class MeterReset(Input):
    old_reading: Decimal = Field(ge=0)
    new_reading: Decimal = Field(ge=0)
    reason: str = Field(min_length=1)
    meter_replaced: bool = False
    recorded_at: datetime


class AssetTransfer(AssetAssignmentCreate):
    ending_meter: Decimal | None = Field(default=None, ge=0)


class LocationEvent(Input):
    location_id: uuid.UUID
    project_id: uuid.UUID | None = None
    event_type: Literal[
        "ASSIGNED",
        "TRANSFERRED",
        "ARRIVED",
        "DEPARTED",
        "RETURNED_TO_YARD",
        "MOVED_TO_WORKSHOP",
        "MOVED_TO_SITE",
        "MANUAL_UPDATE",
        "OTHER",
        "TRANSFER",
    ] = "MANUAL_UPDATE"
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    meter_reading: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class InsuranceCreate(Input):
    provider: str = Field(min_length=1, max_length=200)
    policy_number: str = Field(min_length=1, max_length=150)
    coverage_type: str | None = None
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    start_date: date
    expiry_date: date
    premium_amount: Decimal | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "EXPIRED", "CANCELLED", "PENDING"] = "ACTIVE"
    document_id: uuid.UUID | None = None
    notes: str | None = None


class RegistrationCreate(Input):
    registration_type: Literal[
        "VEHICLE_REGISTRATION",
        "ROADWORTHINESS",
        "OPERATING_PERMIT",
        "INSPECTION_CERTIFICATE",
        "IMPORT_PERMIT",
        "OTHER",
        "Vehicle License",
    ]
    registration_number: str = Field(min_length=1, max_length=100)
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: Literal["ACTIVE", "EXPIRED", "CANCELLED", "PENDING"] = "ACTIVE"
    document_id: uuid.UUID | None = None
    notes: str | None = None


class OwnershipCreate(Input):
    ownership_type: OwnershipType
    owner_or_provider: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    purchase_or_contract_reference: str | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    notes: str | None = None


class MediaCreate(Input):
    media_type: Literal["PHOTO", "VIDEO", "OTHER"] = "PHOTO"
    file_url: str = Field(min_length=1)
    file_name: str | None = None
    caption: str | None = None
    is_primary: bool = False
    captured_at: datetime | None = None


class InspectionCreate(Input):
    inspection_type: Literal[
        "PRE_OPERATION",
        "POST_OPERATION",
        "DAILY",
        "WEEKLY",
        "MONTHLY",
        "MOBILIZATION",
        "DEMOBILIZATION",
        "RETURN_TO_YARD",
        "REGULATORY",
        "OTHER",
        "Pre-Operation",
    ]
    inspection_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    inspected_by_id: uuid.UUID | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0)
    condition_status: Literal[
        "EXCELLENT", "GOOD", "FAIR", "POOR", "UNSAFE", "OUT_OF_SERVICE", "DEFECTIVE"
    ]
    summary: str | None = None
    defects_found: bool = False
    defect_notes: str | None = None
    follow_up_required: bool = False
    document_id: uuid.UUID | None = None


class DefectCreate(Input):
    inspection_id: uuid.UUID | None = None
    reported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    description: str = Field(min_length=1)
    status: Literal["OPEN", "ACKNOWLEDGED"] = "OPEN"
    notes: str | None = None


class ResolveDefect(Input):
    notes: str = Field(min_length=1)


class ComponentRemoval(Input):
    removal_date: date
    notes: str | None = None


class CategoryUpdate(Input):
    code: str | None = Field(default=None, max_length=30)
    default_meter_type: MeterType | None = None
    is_mobile: bool | None = None
    requires_registration: bool | None = None
    requires_insurance: bool | None = None
    requires_operator: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    parent_category_id: uuid.UUID | None = None


class ComponentUpdate(Input):
    parent_component_id: uuid.UUID | None = None
    component_number: str | None = Field(default=None, max_length=50)
    part_number: str | None = Field(default=None, max_length=150)
    expected_life_cycles: Decimal | None = Field(default=None, ge=0)
    removal_date: date | None = None
    is_active: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    component_type: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=150)
    serial_number: str | None = Field(default=None, max_length=150)
    installation_date: date | None = None
    meter_at_installation: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    expected_life_hours: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    status: ComponentStatus | None = None
    notes: str | None = None


class DocumentUpdate(Input):
    document_type: DocumentType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_number: str | None = Field(default=None, max_length=100)
    file_url: str | None = Field(default=None, min_length=1, max_length=1024)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    issuing_authority: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class InsuranceUpdate(Input):
    provider: str | None = Field(default=None, min_length=1, max_length=200)
    policy_number: str | None = Field(default=None, min_length=1, max_length=150)
    coverage_type: str | None = None
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    premium_amount: Decimal | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "EXPIRED", "CANCELLED", "PENDING"] | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = None


class RegistrationUpdate(Input):
    registration_type: (
        Literal[
            "VEHICLE_REGISTRATION",
            "ROADWORTHINESS",
            "OPERATING_PERMIT",
            "INSPECTION_CERTIFICATE",
            "IMPORT_PERMIT",
            "OTHER",
            "Vehicle License",
        ]
        | None
    ) = None
    registration_number: str | None = Field(default=None, min_length=1, max_length=100)
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: Literal["ACTIVE", "EXPIRED", "CANCELLED", "PENDING"] | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = None


class MediaUpdate(Input):
    media_type: Literal["PHOTO", "VIDEO", "OTHER"] | None = None
    file_url: str | None = Field(default=None, min_length=1)
    file_name: str | None = None
    caption: str | None = None
    is_primary: bool | None = None
    captured_at: datetime | None = None


class InspectionUpdate(Input):
    inspection_type: (
        Literal[
            "PRE_OPERATION",
            "POST_OPERATION",
            "DAILY",
            "WEEKLY",
            "MONTHLY",
            "MOBILIZATION",
            "DEMOBILIZATION",
            "RETURN_TO_YARD",
            "REGULATORY",
            "OTHER",
            "Pre-Operation",
        ]
        | None
    ) = None
    inspection_date: datetime | None = Field(default=None)
    project_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    inspected_by_id: uuid.UUID | None = None
    meter_reading: Decimal | None = Field(default=None, ge=0)
    condition_status: (
        Literal["EXCELLENT", "GOOD", "FAIR", "POOR", "UNSAFE", "OUT_OF_SERVICE", "DEFECTIVE"] | None
    ) = None
    summary: str | None = None
    defects_found: bool | None = None
    defect_notes: str | None = None
    follow_up_required: bool | None = None
    document_id: uuid.UUID | None = None


class DefectUpdate(Input):
    inspection_id: uuid.UUID | None = None
    reported_at: datetime | None = Field(default=None)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    description: str | None = Field(default=None, min_length=1)
    status: Literal["OPEN", "ACKNOWLEDGED"] | None = None
    notes: str | None = None

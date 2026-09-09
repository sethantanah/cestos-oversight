import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin
from app.models.employee import AssignmentStatus


class OwnershipType(enum.StrEnum):
    OWNED = "OWNED"
    LEASED = "LEASED"
    RENTED = "RENTED"
    CLIENT_OWNED = "CLIENT_OWNED"
    THIRD_PARTY = "THIRD_PARTY"
    OTHER = "OTHER"


class AssetStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OPERATING = "OPERATING"
    MOBILIZING = "MOBILIZING"
    STANDBY = "STANDBY"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    BREAKDOWN = "BREAKDOWN"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DISPOSED = "DISPOSED"
    DEMOBILIZING = "DEMOBILIZING"
    QUARANTINED = "QUARANTINED"
    LOST = "LOST"
    STOLEN = "STOLEN"


class MeterType(enum.StrEnum):
    ENGINE_HOURS = "ENGINE_HOURS"
    OPERATING_HOURS = "OPERATING_HOURS"
    ODOMETER_KM = "ODOMETER_KM"
    ODOMETER_MILES = "ODOMETER_MILES"
    CYCLES = "CYCLES"
    NONE = "NONE"


class ReadingType(enum.StrEnum):
    ENGINE_HOURS = "ENGINE_HOURS"
    OPERATING_HOURS = "OPERATING_HOURS"
    ODOMETER_KM = "ODOMETER_KM"
    ODOMETER_MILES = "ODOMETER_MILES"
    CYCLES = "CYCLES"


class ComponentStatus(enum.StrEnum):
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"
    FAILED = "FAILED"
    AVAILABLE = "AVAILABLE"
    UNDER_REPAIR = "UNDER_REPAIR"
    SCRAPPED = "SCRAPPED"
    REPLACED = "REPLACED"


class AssetCategory(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "asset_categories"
    __table_args__ = (
        Index("ix_asset_categories_org_name", "organization_id", "name", unique=True),
        Index("ix_asset_categories_parent", "organization_id", "parent_category_id"),
    )

    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(SAText)
    parent_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_categories.id"))

    code: Mapped[str | None] = mapped_column(String(30))
    default_meter_type: Mapped[MeterType | None] = mapped_column(Enum(MeterType, name="meter_type"))
    is_mobile: Mapped[bool] = mapped_column(default=True, server_default="true")
    requires_registration: Mapped[bool] = mapped_column(default=False, server_default="false")
    requires_insurance: Mapped[bool] = mapped_column(default=False, server_default="false")
    requires_operator: Mapped[bool] = mapped_column(default=False, server_default="false")


class Asset(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("purchase_price >= 0", name="asset_purchase_nonnegative"),
        CheckConstraint("current_meter_reading >= 0", name="asset_meter_nonnegative"),
        CheckConstraint("warranty_expiry_date >= warranty_start_date", name="asset_warranty_dates"),
        CheckConstraint("year_of_manufacture BETWEEN 1900 AND 2100", name="asset_year_range"),
        Index("ix_assets_org_serial", "organization_id", "serial_number", unique=True),
        Index("ix_assets_org_registration", "organization_id", "registration_number"),
        Index("ix_assets_org_operator", "organization_id", "primary_operator_id"),
        Index("ix_assets_org_number", "organization_id", "asset_number", unique=True),
        Index("ix_assets_org_category", "organization_id", "category_id"),
        Index("ix_assets_org_status", "organization_id", "status"),
        Index("ix_assets_org_responsible", "organization_id", "responsible_employee_id"),
        Index("ix_assets_org_location", "organization_id", "default_location_id"),
    )

    asset_number: Mapped[str] = mapped_column(String(30))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(SAText)
    manufacturer: Mapped[str | None] = mapped_column(String(150))
    model: Mapped[str | None] = mapped_column(String(150))
    serial_number: Mapped[str | None] = mapped_column(String(150))
    year_of_manufacture: Mapped[int | None]
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ownership_type: Mapped[OwnershipType] = mapped_column(
        Enum(OwnershipType, name="ownership_type"), default=OwnershipType.OWNED
    )
    engine_number: Mapped[str | None] = mapped_column(String(150))
    registration_number: Mapped[str | None] = mapped_column(String(100))
    meter_type: Mapped[MeterType] = mapped_column(
        Enum(MeterType, name="meter_type"), default=MeterType.NONE
    )
    current_meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), default=AssetStatus.AVAILABLE
    )
    default_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    responsible_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    photo_url: Mapped[str | None] = mapped_column(String(1024))
    warranty_expiry_date: Mapped[date | None] = mapped_column(Date)
    insurance_expiry_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(SAText)

    engine_manufacturer: Mapped[str | None] = mapped_column(String(150))
    engine_model: Mapped[str | None] = mapped_column(String(150))
    chassis_number: Mapped[str | None] = mapped_column(String(150))
    vin: Mapped[str | None] = mapped_column(String(150))
    ownership_entity: Mapped[str | None] = mapped_column(String(200))
    purchase_currency: Mapped[str | None] = mapped_column(String(10))
    commission_date: Mapped[date | None] = mapped_column(Date)
    supplier_id: Mapped[uuid.UUID | None]
    warranty_start_date: Mapped[date | None] = mapped_column(Date)
    expected_service_life_years: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    residual_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    primary_operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    profile_photo_url: Mapped[str | None] = mapped_column(SAText)
    qr_code_value: Mapped[str | None] = mapped_column(String(255))
    barcode_value: Mapped[str | None] = mapped_column(String(255))


class AssetComponent(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "asset_components"
    __table_args__ = (Index("ix_asset_components_asset", "organization_id", "asset_id"),)

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    component_type: Mapped[str | None] = mapped_column(String(100))
    manufacturer: Mapped[str | None] = mapped_column(String(150))
    model: Mapped[str | None] = mapped_column(String(150))
    serial_number: Mapped[str | None] = mapped_column(String(150))
    installation_date: Mapped[date | None] = mapped_column(Date)
    meter_at_installation: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expected_life_hours: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[ComponentStatus] = mapped_column(
        Enum(ComponentStatus, name="component_status"), default=ComponentStatus.INSTALLED
    )
    notes: Mapped[str | None] = mapped_column(SAText)

    parent_component_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_components.id"))
    component_number: Mapped[str | None] = mapped_column(String(50))
    part_number: Mapped[str | None] = mapped_column(String(150))
    expected_life_cycles: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    removal_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class AssetAssignment(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "asset_assignments"
    __table_args__ = (
        Index(
            "uq_asset_active_assignment",
            "organization_id",
            "asset_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint("returned_at >= assigned_at", name="asset_assignment_dates"),
        CheckConstraint("ending_meter >= starting_meter", name="asset_assignment_meters"),
        Index("ix_asset_assignments_number", "organization_id", "assignment_number", unique=True),
        Index("ix_asset_assignments_asset", "organization_id", "asset_id", "status"),
        Index("ix_asset_assignments_project", "organization_id", "project_id", "status"),
    )

    assignment_number: Mapped[str] = mapped_column(String(20))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    responsible_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starting_meter: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ending_meter: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, name="asset_assignment_status"),
        default=AssignmentStatus.PLANNED,
    )
    notes: Mapped[str | None] = mapped_column(SAText)

    primary_operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignment_reason: Mapped[str | None] = mapped_column(String(200))


class AssetMeterReading(UUIDMixin, OrganizationMixin, Base):
    __tablename__ = "asset_meter_readings"
    __table_args__ = (
        Index("ix_meter_readings_asset_time", "organization_id", "asset_id", "recorded_at"),
        Index("ix_meter_readings_asset_type", "organization_id", "asset_id", "reading_type"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    reading: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reading_type: Mapped[ReadingType] = mapped_column(Enum(ReadingType, name="reading_type"))
    source: Mapped[str | None] = mapped_column(String(50))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(SAText)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    evidence_photo_url: Mapped[str | None] = mapped_column(SAText)
    is_adjustment: Mapped[bool] = mapped_column(default=False, server_default="false")
    adjustment_reason: Mapped[str | None] = mapped_column(SAText)
    previous_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    meter_replaced: Mapped[bool] = mapped_column(default=False, server_default="false")


class AssetDocumentType(enum.StrEnum):
    CV = "CV"
    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    WORK_PERMIT = "WORK_PERMIT"
    EMPLOYMENT_CONTRACT = "EMPLOYMENT_CONTRACT"
    MEDICAL_CERTIFICATE = "MEDICAL_CERTIFICATE"
    SAFETY_CERTIFICATE = "SAFETY_CERTIFICATE"
    TRAINING_CERTIFICATE = "TRAINING_CERTIFICATE"
    EDUCATIONAL_CERTIFICATE = "EDUCATIONAL_CERTIFICATE"
    TRADE_CERTIFICATE = "TRADE_CERTIFICATE"
    PROFESSIONAL_CERTIFICATE = "PROFESSIONAL_CERTIFICATE"
    INSURANCE_DOCUMENT = "INSURANCE_DOCUMENT"
    POLICE_CLEARANCE = "POLICE_CLEARANCE"
    OTHER = "OTHER"
    PURCHASE_DOCUMENT = "PURCHASE_DOCUMENT"
    OWNERSHIP_DOCUMENT = "OWNERSHIP_DOCUMENT"
    REGISTRATION = "REGISTRATION"
    INSURANCE = "INSURANCE"
    WARRANTY = "WARRANTY"
    INSPECTION_CERTIFICATE = "INSPECTION_CERTIFICATE"
    ROADWORTHINESS = "ROADWORTHINESS"
    IMPORT_DOCUMENT = "IMPORT_DOCUMENT"
    MANUFACTURER_MANUAL = "MANUFACTURER_MANUAL"
    SERVICE_MANUAL = "SERVICE_MANUAL"
    PARTS_MANUAL = "PARTS_MANUAL"
    CALIBRATION_CERTIFICATE = "CALIBRATION_CERTIFICATE"
    LEASE_AGREEMENT = "LEASE_AGREEMENT"
    RENTAL_AGREEMENT = "RENTAL_AGREEMENT"
    PHOTO = "PHOTO"


class AssetDocument(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "asset_documents"
    __table_args__ = (
        Index("ix_asset_documents_asset", "organization_id", "asset_id"),
        Index("ix_asset_documents_expiry", "organization_id", "expiry_date"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    document_type: Mapped[AssetDocumentType] = mapped_column(
        Enum(AssetDocumentType, name="asset_document_type"), default=AssetDocumentType.OTHER
    )
    title: Mapped[str] = mapped_column(String(200))
    document_number: Mapped[str | None] = mapped_column(String(100))
    file_url: Mapped[str] = mapped_column(String(1024))
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    issuing_authority: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(SAText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    file_size: Mapped[int | None]
    verification_status: Mapped[str] = mapped_column(
        String(30), default="PENDING", server_default="PENDING"
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

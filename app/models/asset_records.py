"""Normalized equipment compliance and operational history."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class AssetRecord(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin):
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)


class AssetLocationHistory(AssetRecord, Base):
    __tablename__ = "asset_location_history"
    __table_args__ = (
        Index("ix_asset_location_time", "organization_id", "asset_id", "recorded_at"),
    )
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source_reference_type: Mapped[str | None] = mapped_column(String(80))
    source_reference_id: Mapped[uuid.UUID | None]
    notes: Mapped[str | None] = mapped_column(Text)


class AssetStatusHistory(AssetRecord, Base):
    __tablename__ = "asset_status_history"
    __table_args__ = (Index("ix_asset_status_time", "organization_id", "asset_id", "changed_at"),)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    source_reference_type: Mapped[str | None] = mapped_column(String(80))
    source_reference_id: Mapped[uuid.UUID | None]


class AssetInsurance(AssetRecord, Base):
    __tablename__ = "asset_insurance_records"
    __table_args__ = (
        CheckConstraint("expiry_date >= start_date", name="insurance_dates"),
        CheckConstraint("coverage_amount >= 0 AND premium_amount >= 0", name="insurance_amounts"),
        Index("ix_insurance_expiry", "organization_id", "expiry_date"),
    )
    provider: Mapped[str] = mapped_column(String(200))
    policy_number: Mapped[str] = mapped_column(String(150))
    coverage_type: Mapped[str | None] = mapped_column(String(100))
    coverage_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    start_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date)
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_documents.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class AssetRegistration(AssetRecord, Base):
    __tablename__ = "asset_registrations"
    __table_args__ = (
        CheckConstraint("expiry_date >= issue_date", name="registration_dates"),
        Index("ix_registration_expiry", "organization_id", "expiry_date"),
    )
    registration_type: Mapped[str] = mapped_column(String(40))
    registration_number: Mapped[str] = mapped_column(String(100))
    issuing_authority: Mapped[str | None] = mapped_column(String(200))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_documents.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class AssetOwnership(AssetRecord, Base):
    __tablename__ = "asset_ownership_history"
    __table_args__ = (CheckConstraint("end_date >= start_date", name="ownership_dates"),)
    ownership_type: Mapped[str] = mapped_column(String(30))
    owner_or_provider: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    purchase_or_contract_reference: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(Text)


class AssetMedia(AssetRecord, Base):
    __tablename__ = "asset_media"
    __table_args__ = (
        Index(
            "uq_asset_primary_media",
            "organization_id",
            "asset_id",
            unique=True,
            postgresql_where=text("is_primary AND is_active"),
        ),
    )
    media_type: Mapped[str] = mapped_column(String(20), default="PHOTO")
    file_url: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class AssetInspection(AssetRecord, Base):
    __tablename__ = "asset_inspections"
    __table_args__ = (
        Index("ix_inspection_date", "organization_id", "asset_id", "inspection_date"),
    )
    inspection_type: Mapped[str] = mapped_column(String(40))
    inspection_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    inspected_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    condition_status: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str | None] = mapped_column(Text)
    defects_found: Mapped[bool] = mapped_column(default=False)
    defect_notes: Mapped[str | None] = mapped_column(Text)
    follow_up_required: Mapped[bool] = mapped_column(default=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_documents.id"))


class AssetDefect(AssetRecord, Base):
    __tablename__ = "asset_defects"
    __table_args__ = (
        Index("ix_asset_defect_state", "organization_id", "asset_id", "status", "severity"),
    )
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_inspections.id"))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reported_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

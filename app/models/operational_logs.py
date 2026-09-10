"""Asset operating logs and project collaboration records."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class AssetFuelLog(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "asset_fuel_logs"
    __table_args__ = (
        CheckConstraint("quantity_litres > 0 AND unit_cost >= 0", name="fuel_positive"),
        Index("ix_asset_fuel_time", "organization_id", "asset_id", "recorded_at"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fuel_type: Mapped[str] = mapped_column(String(30))
    quantity_litres: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(3))
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    supplier: Mapped[str | None] = mapped_column(String(200))
    reference_number: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)


class AssetMaintenanceJob(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "asset_maintenance_jobs"
    __table_args__ = (
        CheckConstraint("cost >= 0", name="maintenance_cost_positive"),
        CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','COMPLETED','CANCELLED')", name="maintenance_status"
        ),
        Index("ix_asset_maintenance_status", "organization_id", "asset_id", "status"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    maintenance_type: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    scheduled_date: Mapped[date | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    provider: Mapped[str | None] = mapped_column(String(200))
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3))
    completion_notes: Mapped[str | None] = mapped_column(Text)


class ProjectRecord(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "project_records"
    __table_args__ = (
        CheckConstraint("record_type IN ('FILE','NOTE','COMMENT')", name="project_record_type"),
        Index("ix_project_record_time", "organization_id", "project_id", "created_at"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    record_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None]


class FuelSupplier(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "fuel_suppliers"
    __table_args__ = (Index("ix_fuel_supplier_name", "organization_id", "name"),)
    name: Mapped[str] = mapped_column(String(200))


class AssetFuelReduction(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "asset_fuel_reductions"
    __table_args__ = (
        CheckConstraint("litres_reduced > 0", name="fuel_reduction_positive"),
        Index("ix_asset_fuel_reduction_time", "organization_id", "asset_id", "recorded_at"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    fuel_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_fuel_logs.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    litres_reduced: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    remaining_litres: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    reduction_reason: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)


class AssetLogFile(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "asset_log_files"
    __table_args__ = (
        Index("ix_asset_log_files_lookup", "organization_id", "asset_id", "log_type", "log_id"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    log_type: Mapped[str] = mapped_column(String(30))  # MAINTENANCE, FUEL, INSPECTION, METER
    log_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    storage_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None]

"""Asset operating logs and project collaboration records."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ArchiveMixin, ActorMixin, OrganizationMixin, TimestampMixin, UUIDMixin


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


class FuelDelivery(UUIDMixin, OrganizationMixin, TimestampMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "fuel_deliveries"
    __table_args__ = (CheckConstraint("quantity_litres > 0", name="fuel_delivery_positive"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    site_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fuel_type: Mapped[str] = mapped_column(String(30))
    quantity_litres: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    supplier: Mapped[str | None] = mapped_column(String(200))
    reference_number: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    receipt_path: Mapped[str | None] = mapped_column(Text)
    receipt_file_name: Mapped[str | None] = mapped_column(String(255))
    receipt_mime_type: Mapped[str | None] = mapped_column(String(150))
    receipt_size_bytes: Mapped[int | None]


class FuelAllocation(UUIDMixin, OrganizationMixin, TimestampMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "fuel_allocations"
    __table_args__ = (CheckConstraint("quantity_litres > 0", name="fuel_allocation_positive"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    site_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fuel_deliveries.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity_litres: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    notes: Mapped[str | None] = mapped_column(Text)


class PMTemplate(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "pm_templates"
    name: Mapped[str] = mapped_column(String(200))
    equipment_type: Mapped[str | None] = mapped_column(String(100))
    pm_interval: Mapped[str] = mapped_column(String(100))
    inspection_items: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class PMJobCard(UUIDMixin, OrganizationMixin, TimestampMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "pm_job_cards"
    # Keep inserts working against databases where an earlier PM migration did
    # not install the timestamp defaults yet; the follow-up migration repairs
    # the database defaults for non-ORM inserts as well.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=lambda: datetime.now(timezone.utc))
    job_card_number: Mapped[str] = mapped_column(String(50), unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    site_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("maintenance_work_orders.id"), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pm_templates.id"))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    pm_control: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    inspection_items: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    service_defect_control: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    machine_release: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    technicians: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    signatures: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    supervisor_comments: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BreakdownJobCard(UUIDMixin, OrganizationMixin, TimestampMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "breakdown_job_cards"
    job_card_number: Mapped[str] = mapped_column(String(50), unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    site_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("maintenance_work_orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    job_control: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    reported_failure: Mapped[str | None] = mapped_column(Text)
    corrective_action: Mapped[str | None] = mapped_column(Text)
    parts_materials: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    labour_downtime: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    test_release: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    signatures: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class OperationalPayee(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "operational_payees"
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    bank_account_details: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class OperationalExpense(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "operational_expenses"
    expense_number: Mapped[str] = mapped_column(String(50), unique=True)
    submitted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True)
    payee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operational_payees.id"))
    pay_to_name: Mapped[str] = mapped_column(String(200))
    pay_to_phone: Mapped[str | None] = mapped_column(String(50))
    bank_account_details: Mapped[str | None] = mapped_column(Text)
    expense_date: Mapped[date] = mapped_column()
    payment_method: Mapped[str] = mapped_column(String(40))
    items: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="SUBMITTED", index=True)
    invoice_path: Mapped[str | None] = mapped_column(Text)
    invoice_name: Mapped[str | None] = mapped_column(String(255))
    invoice_mime_type: Mapped[str | None] = mapped_column(String(150))
    invoice_size_bytes: Mapped[int | None]
    receipt_path: Mapped[str | None] = mapped_column(Text)
    receipt_name: Mapped[str | None] = mapped_column(String(255))
    receipt_mime_type: Mapped[str | None] = mapped_column(String(150))
    receipt_size_bytes: Mapped[int | None]
    paid_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    extracted_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class OperationalExpensePayment(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    """A single finance disbursement against an operational expense."""
    __tablename__ = "operational_expense_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="operational_expense_payment_positive"),
        Index("ix_operational_expense_payment_expense", "organization_id", "expense_id", "payment_date"),
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operational_expenses.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payment_date: Mapped[date] = mapped_column()
    receipt_path: Mapped[str] = mapped_column(Text)
    receipt_name: Mapped[str] = mapped_column(String(255))
    receipt_mime_type: Mapped[str | None] = mapped_column(String(150))
    receipt_size_bytes: Mapped[int | None]
    paid_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reference: Mapped[str | None] = mapped_column(String(120))
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
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    checklist: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    field_notes: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_recurring: Mapped[bool] = mapped_column(default=False, server_default="false")
    recurrence_interval_days: Mapped[int | None] = mapped_column(nullable=True)


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

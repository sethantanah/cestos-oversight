import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class WorkOrderType(enum.StrEnum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"
    EMERGENCY = "EMERGENCY"
    OVERHAUL = "OVERHAUL"


class WorkOrderPriority(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkOrderStatus(enum.StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_PARTS = "WAITING_PARTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FailureTaxonomy(enum.StrEnum):
    MECHANICAL = "MECHANICAL"
    HYDRAULIC = "HYDRAULIC"
    ELECTRICAL = "ELECTRICAL"
    ENGINE = "ENGINE"
    STRUCTURAL = "STRUCTURAL"
    TYRES_TRACKS = "TYRES_TRACKS"
    OPERATOR_ERROR = "OPERATOR_ERROR"


class HseIncidentType(enum.StrEnum):
    NEAR_MISS = "NEAR_MISS"
    FIRST_AID = "FIRST_AID"
    MEDICAL_TREATMENT = "MEDICAL_TREATMENT"
    LOST_TIME_INJURY = "LOST_TIME_INJURY"
    ENVIRONMENTAL_SPILL = "ENVIRONMENTAL_SPILL"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    FATALITY = "FATALITY"


class HseSeverity(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class HseIncidentStatus(enum.StrEnum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CORRECTIVE_ACTION_PENDING = "CORRECTIVE_ACTION_PENDING"
    CLOSED = "CLOSED"


class HseActionStatus(enum.StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class MaintenanceWorkOrder(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "maintenance_work_orders"
    __table_args__ = (
        Index("ix_maintenance_wo_org_asset", "organization_id", "asset_id"),
        Index("ix_maintenance_wo_org_status", "organization_id", "status"),
        Index("ix_maintenance_wo_number", "organization_id", "wo_number", unique=True),
    )

    wo_number: Mapped[str] = mapped_column(String(50))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    defect_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_defects.id"), index=True)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset_inspections.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    work_type: Mapped[WorkOrderType] = mapped_column(Enum(WorkOrderType, name="wo_type", native_enum=False), default=WorkOrderType.CORRECTIVE)
    priority: Mapped[WorkOrderPriority] = mapped_column(Enum(WorkOrderPriority, name="wo_priority", native_enum=False), default=WorkOrderPriority.MEDIUM)
    status: Mapped[WorkOrderStatus] = mapped_column(Enum(WorkOrderStatus, name="wo_status", native_enum=False), default=WorkOrderStatus.OPEN)
    failure_taxonomy: Mapped[FailureTaxonomy | None] = mapped_column(Enum(FailureTaxonomy, name="failure_taxonomy", native_enum=False))

    root_cause: Mapped[str | None] = mapped_column(Text)
    remedy: Mapped[str | None] = mapped_column(Text)
    downtime_hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.0"))
    estimated_lost_contribution: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))

    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    meter_reading: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    checklist: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
    field_notes: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    cost_lines: Mapped[list["WorkOrderCostLine"]] = relationship(
        "WorkOrderCostLine", back_populates="work_order", cascade="all, delete-orphan", lazy="selectin"
    )


class WorkOrderCostLine(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "work_order_cost_lines"
    __table_args__ = (
        Index("ix_wo_cost_lines_org_wo", "organization_id", "work_order_id"),
    )

    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("maintenance_work_orders.id", ondelete="CASCADE"), index=True)
    cost_type: Mapped[str] = mapped_column(String(30))  # PARTS, LABOUR, SUBCONTRACTOR
    description: Mapped[str] = mapped_column(String(255))
    part_number: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    posted_to_subledger: Mapped[bool] = mapped_column(default=False, server_default="false")

    work_order: Mapped["MaintenanceWorkOrder"] = relationship("MaintenanceWorkOrder", back_populates="cost_lines")


class HseIncident(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "hse_incidents"
    __table_args__ = (
        Index("ix_hse_incidents_org_project", "organization_id", "project_id"),
        Index("ix_hse_incidents_org_status", "organization_id", "status"),
        Index("ix_hse_incidents_number", "organization_id", "incident_number", unique=True),
    )

    incident_number: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    incident_type: Mapped[HseIncidentType] = mapped_column(Enum(HseIncidentType, name="hse_incident_type", native_enum=False))
    severity: Mapped[HseSeverity] = mapped_column(Enum(HseSeverity, name="hse_severity", native_enum=False), default=HseSeverity.MEDIUM)
    status: Mapped[HseIncidentStatus] = mapped_column(Enum(HseIncidentStatus, name="hse_incident_status", native_enum=False), default=HseIncidentStatus.REPORTED)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    site_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    reported_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))

    description: Mapped[str] = mapped_column(Text)
    immediate_actions_taken: Mapped[str | None] = mapped_column(Text)
    root_cause_analysis: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    actions: Mapped[list["HseCorrectiveAction"]] = relationship(
        "HseCorrectiveAction", back_populates="incident", cascade="all, delete-orphan", lazy="selectin"
    )


class HseCorrectiveAction(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "hse_corrective_actions"
    __table_args__ = (
        Index("ix_hse_actions_org_incident", "organization_id", "incident_id"),
        Index("ix_hse_actions_org_assignee", "organization_id", "assigned_to_id"),
        Index("ix_hse_actions_org_status", "organization_id", "status"),
    )

    action_number: Mapped[str] = mapped_column(String(50))
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hse_incidents.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    assigned_to_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[HseActionStatus] = mapped_column(Enum(HseActionStatus, name="hse_action_status", native_enum=False), default=HseActionStatus.OPEN)

    closure_notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    incident: Mapped["HseIncident"] = relationship("HseIncident", back_populates="actions")

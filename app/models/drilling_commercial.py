import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class ContractStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class RateType(enum.StrEnum):
    DRILLING_METER = "DRILLING_METER"
    STANDBY_HOURLY = "STANDBY_HOURLY"
    MOBILIZATION_FLAT = "MOBILIZATION_FLAT"
    DEMOBILIZATION_FLAT = "DEMOBILIZATION_FLAT"
    DAYWORK_HOURLY = "DAYWORK_HOURLY"


class CostCategory(enum.StrEnum):
    LABOUR = "LABOUR"
    FUEL = "FUEL"
    MAINTENANCE_PARTS = "MAINTENANCE_PARTS"
    CONSUMABLES = "CONSUMABLES"
    LOGISTICS = "LOGISTICS"
    CAMP = "CAMP"
    SUBCONTRACTOR = "SUBCONTRACTOR"
    OVERHEAD = "OVERHEAD"


class RevenueCategory(enum.StrEnum):
    DRILLING_METERAGE = "DRILLING_METERAGE"
    STANDBY_TIME = "STANDBY_TIME"
    MOBILIZATION = "MOBILIZATION"
    DAYWORK = "DAYWORK"
    REIMBURSABLE = "REIMBURSABLE"


class ProjectContract(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "project_contracts"
    __table_args__ = (
        Index("ix_project_contracts_org_proj", "organization_id", "project_id"),
        Index("ix_project_contracts_org_status", "organization_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    contract_number: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus, name="contract_status", native_enum=False), default=ContractStatus.ACTIVE
    )
    notes: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict] | None] = mapped_column(JSONB, default=list)

    rate_cards: Mapped[list["ContractRateCard"]] = relationship(
        "ContractRateCard", back_populates="contract", cascade="all, delete-orphan", lazy="selectin"
    )


class ContractRateCard(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "contract_rate_cards"
    __table_args__ = (
        Index("ix_contract_rate_cards_org_contract", "organization_id", "contract_id"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project_contracts.id", ondelete="CASCADE"), index=True)
    rate_type: Mapped[RateType] = mapped_column(Enum(RateType, name="rate_type", native_enum=False))
    drilling_method: Mapped[str | None] = mapped_column(String(100))
    depth_from_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    depth_to_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(String(255))

    contract: Mapped["ProjectContract"] = relationship("ProjectContract", back_populates="rate_cards")


class CostSubledgerEntry(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "cost_subledger_entries"
    __table_args__ = (
        Index("ix_cost_subledger_org_project", "organization_id", "project_id"),
        Index("ix_cost_subledger_org_rig", "organization_id", "rig_id"),
        Index("ix_cost_subledger_org_category", "organization_id", "cost_category"),
        Index("ix_cost_subledger_posted", "organization_id", "posted_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    rig_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), index=True)
    shift_report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drilling_shift_reports.id"), index=True)
    cost_category: Mapped[CostCategory] = mapped_column(Enum(CostCategory, name="cost_category", native_enum=False))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    unit_of_measure: Mapped[str] = mapped_column(String(30))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    exchange_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))
    total_cost_base: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    source_entity_type: Mapped[str | None] = mapped_column(String(50))
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text)


class RevenueSubledgerEntry(UUIDMixin, TimestampMixin, OrganizationMixin, ActorMixin, Base):
    __tablename__ = "revenue_subledger_entries"
    __table_args__ = (
        Index("ix_revenue_subledger_org_project", "organization_id", "project_id"),
        Index("ix_revenue_subledger_org_rig", "organization_id", "rig_id"),
        Index("ix_revenue_subledger_org_shift", "organization_id", "shift_report_id"),
        Index("ix_revenue_subledger_posted", "organization_id", "posted_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    rig_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"), index=True)
    shift_report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drilling_shift_reports.id"), index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("project_contracts.id"), index=True)
    rate_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_rate_cards.id"), index=True)
    revenue_category: Mapped[RevenueCategory] = mapped_column(Enum(RevenueCategory, name="revenue_category", native_enum=False))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    exchange_rate_to_base: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.000000"))
    total_revenue_base: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text)

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class TenderStage(enum.StrEnum):
    PROSPECT = "PROSPECT"
    QUALIFIED = "QUALIFIED"
    PROPOSAL_SENT = "PROPOSAL_SENT"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class ClientArtifactType(enum.StrEnum):
    SHIFT_REPORT = "SHIFT_REPORT"
    HOLE_LOG = "HOLE_LOG"
    PROGRESS_SUMMARY = "PROGRESS_SUMMARY"
    PHOTO = "PHOTO"
    INVOICE_STATEMENT = "INVOICE_STATEMENT"


class SupervisorScorecard(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "supervisor_scorecards"
    __table_args__ = (
        Index("ix_supervisor_scorecards_org_sup", "organization_id", "supervisor_id"),
        Index("ix_supervisor_scorecards_org_period", "organization_id", "period_start", "period_end"),
    )

    scorecard_number: Mapped[str] = mapped_column(String(50))
    supervisor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    # 8 Weighted Pillars
    production_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))      # Max 25%
    rig_condition_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))   # Max 20%
    downtime_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))        # Max 15%
    hse_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))             # Max 15%
    consumables_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))      # Max 10%
    crew_management_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))  # Max 5%
    reporting_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))        # Max 5%
    stewardship_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))      # Max 5%

    overall_weighted_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0")) # Max 100%
    grade: Mapped[str] = mapped_column(String(10), default="C")
    notes: Mapped[str | None] = mapped_column(Text)


class CommercialOpportunity(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "commercial_opportunities"
    __table_args__ = (
        Index("ix_commercial_opps_org_client", "organization_id", "client_id"),
        Index("ix_commercial_opps_org_stage", "organization_id", "tender_stage"),
    )

    opportunity_number: Mapped[str] = mapped_column(String(50))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    tender_stage: Mapped[TenderStage] = mapped_column(Enum(TenderStage, name="tender_stage", native_enum=False), default=TenderStage.PROSPECT)
    win_probability_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("50.0"))
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.0"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class ClientProjectGrant(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "client_project_grants"
    __table_args__ = (
        Index("ix_client_grants_client_proj", "organization_id", "client_id", "project_id", unique=True),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ClientPublishedArtifact(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "client_published_artifacts"
    __table_args__ = (
        Index("ix_client_published_proj", "organization_id", "client_id", "project_id"),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    artifact_type: Mapped[ClientArtifactType] = mapped_column(Enum(ClientArtifactType, name="client_artifact_type", native_enum=False))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    published_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

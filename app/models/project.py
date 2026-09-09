import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class ProjectStatus(enum.StrEnum):
    PLANNING = "PLANNING"
    MOBILIZING = "MOBILIZING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Project(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_org_number", "organization_id", "project_number", unique=True),
        Index("ix_projects_org_client", "organization_id", "client_id"),
        Index("ix_projects_org_status", "organization_id", "status"),
        Index("ix_projects_org_manager", "organization_id", "project_manager_id"),
    )

    project_number: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(SAText)
    project_type: Mapped[str | None] = mapped_column(String(100))
    drilling_type: Mapped[str | None] = mapped_column(String(100))
    contract_number: Mapped[str | None] = mapped_column(String(100))
    project_manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    expected_end_date: Mapped[date | None] = mapped_column(Date)
    actual_end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.PLANNING
    )
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    target_metres: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(SAText)

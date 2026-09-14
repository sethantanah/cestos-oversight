"""Immutable, attributed project field reports."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class ProjectReport(UUIDMixin, OrganizationMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "project_reports"
    __table_args__ = (
        Index("ix_project_reports_date", "organization_id", "project_id", "report_date"),
        CheckConstraint(
            "report_type IN ('DRILLING_UPDATE','PROGRESS_UPDATE','SAFETY_REPORT','SITE_ISSUE')",
            name="project_report_type",
        ),
        CheckConstraint(
            "metres >= 0 AND drill_holes >= 0 AND average_depth >= 0",
            name="project_report_positive",
        ),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    site_name: Mapped[str] = mapped_column(String(200))
    report_type: Mapped[str] = mapped_column(String(30))
    report_date: Mapped[date]
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    metres: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    drill_holes: Mapped[int | None]
    average_depth: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    author_name: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None]

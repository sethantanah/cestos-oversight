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
)
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import (
    ActorMixin,
    ArchiveMixin,
    OrganizationMixin,
    TimestampMixin,
    UUIDMixin,
)


class DrillingProgramStatus(enum.StrEnum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DrillHoleStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ShiftType(enum.StrEnum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class ShiftReportStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class TimeCategory(enum.StrEnum):
    PRODUCTIVE = "PRODUCTIVE"
    STANDBY = "STANDBY"
    MAINTENANCE = "MAINTENANCE"
    NON_PRODUCTIVE = "NON_PRODUCTIVE"


class DrillingProgram(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "drilling_programs"
    __table_args__ = (
        Index("ix_drilling_programs_org_project", "organization_id", "project_id"),
        Index("ix_drilling_programs_org_status", "organization_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(50))
    target_metres: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[DrillingProgramStatus] = mapped_column(
        Enum(DrillingProgramStatus, name="drilling_program_status"),
        default=DrillingProgramStatus.PLANNING,
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(SAText)
    notes: Mapped[str | None] = mapped_column(SAText)


class DrillHole(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "drill_holes"
    __table_args__ = (
        Index("ix_drill_holes_org_project", "organization_id", "project_id"),
        Index("ix_drill_holes_org_program", "organization_id", "program_id"),
        Index("ix_drill_holes_number", "organization_id", "project_id", "hole_number", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    program_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drilling_programs.id"), index=True)
    hole_number: Mapped[str] = mapped_column(String(100))
    drilling_method: Mapped[str | None] = mapped_column(String(100))
    target_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    final_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    azimuth_deg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    dip_deg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[DrillHoleStatus] = mapped_column(
        Enum(DrillHoleStatus, name="drill_hole_status"),
        default=DrillHoleStatus.PLANNED,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(SAText)


class DrillingShiftReport(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "drilling_shift_reports"
    __table_args__ = (
        Index("ix_drilling_shifts_org_project", "organization_id", "project_id"),
        Index("ix_drilling_shifts_org_rig", "organization_id", "rig_id"),
        Index("ix_drilling_shifts_org_date", "organization_id", "date"),
        Index("ix_drilling_shifts_org_status", "organization_id", "status"),
        Index("uq_drilling_shifts_rig_date_shift", "organization_id", "rig_id", "date", "shift_type", unique=True),
    )

    report_number: Mapped[str] = mapped_column(String(30))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    rig_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    program_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drilling_programs.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    shift_type: Mapped[ShiftType] = mapped_column(
        Enum(ShiftType, name="shift_type"), default=ShiftType.DAY
    )
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[ShiftReportStatus] = mapped_column(
        Enum(ShiftReportStatus, name="shift_report_status"),
        default=ShiftReportStatus.DRAFT,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    return_reason: Mapped[str | None] = mapped_column(SAText)
    correction_reason: Mapped[str | None] = mapped_column(SAText)
    total_metres: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.0"))
    total_productive_hours: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.0"))
    total_nonproductive_hours: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.0"))
    avg_core_recovery_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    notes: Mapped[str | None] = mapped_column(SAText)

    intervals: Mapped[list["DrillingShiftInterval"]] = relationship(
        "DrillingShiftInterval",
        back_populates="shift_report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    time_segments: Mapped[list["DrillingShiftTimeSegment"]] = relationship(
        "DrillingShiftTimeSegment",
        back_populates="shift_report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    crew_members: Mapped[list["DrillingShiftCrew"]] = relationship(
        "DrillingShiftCrew",
        back_populates="shift_report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DrillingShiftInterval(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "drilling_shift_intervals"
    __table_args__ = (
        CheckConstraint("to_depth_m >= from_depth_m", name="ck_interval_depth"),
        Index("ix_shift_intervals_report", "organization_id", "shift_report_id"),
        Index("ix_shift_intervals_hole", "organization_id", "drill_hole_id"),
    )

    shift_report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), index=True)
    drill_hole_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drill_holes.id"), index=True)
    from_depth_m: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    to_depth_m: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    drilled_metres: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    core_recovered_m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    core_recovery_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    drilling_method: Mapped[str | None] = mapped_column(String(50))
    ground_conditions: Mapped[str | None] = mapped_column(String(200))

    shift_report: Mapped["DrillingShiftReport"] = relationship(
        "DrillingShiftReport", back_populates="intervals"
    )


class DrillingShiftTimeSegment(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "drilling_shift_time_segments"
    __table_args__ = (
        CheckConstraint("hours >= 0", name="ck_time_segment_hours"),
        Index("ix_shift_time_segments_report", "organization_id", "shift_report_id"),
    )

    shift_report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), index=True)
    category: Mapped[TimeCategory] = mapped_column(Enum(TimeCategory, name="time_category"))
    reason_code: Mapped[str] = mapped_column(String(100))
    hours: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    comments: Mapped[str | None] = mapped_column(SAText)

    shift_report: Mapped["DrillingShiftReport"] = relationship(
        "DrillingShiftReport", back_populates="time_segments"
    )


class DrillingShiftCrew(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "drilling_shift_crews"
    __table_args__ = (
        Index("ix_shift_crews_report", "organization_id", "shift_report_id"),
        Index("ix_shift_crews_employee", "organization_id", "employee_id"),
    )

    shift_report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    role_on_shift: Mapped[str] = mapped_column(String(100))
    hours_worked: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("12.0"))

    shift_report: Mapped["DrillingShiftReport"] = relationship(
        "DrillingShiftReport", back_populates="crew_members"
    )

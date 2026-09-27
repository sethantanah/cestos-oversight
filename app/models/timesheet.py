import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import ActorMixin, TimestampMixin, UUIDMixin


class EmployeeTimesheet(UUIDMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "employee_timesheets"
    __table_args__ = (
        Index("ix_employee_timesheets_org_period", "organization_id", "period_start"),
        Index("ix_employee_timesheets_org_employee_period", "organization_id", "employee_id", "period_start"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(200))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    project_name: Mapped[str | None] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    site_name: Mapped[str | None] = mapped_column(String(200))
    source_file: Mapped[str | None] = mapped_column(String(255))
    days: Mapped[list["EmployeeTimesheetDay"]] = relationship(
        back_populates="timesheet", cascade="all, delete-orphan", order_by="EmployeeTimesheetDay.work_date"
    )


class EmployeeTimesheetDay(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "employee_timesheet_days"
    __table_args__ = (
        UniqueConstraint("timesheet_id", "work_date", name="uq_employee_timesheet_day"),
        CheckConstraint("hours >= 0 AND hours <= 24", name="ck_employee_timesheet_hours_range"),
        Index("ix_employee_timesheet_days_date", "work_date"),
    )

    timesheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employee_timesheets.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    timesheet: Mapped[EmployeeTimesheet] = relationship(back_populates="days")

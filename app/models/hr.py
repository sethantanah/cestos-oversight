"""HR compensation, reminders and employee account lifecycle."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import OrganizationMixin, TimestampMixin, UUIDMixin


class Salary(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "employee_salaries"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="salary_nonnegative"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="salary_dates"),
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    pay_period: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(2000))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class ContractAlertRule(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "contract_alert_rules"
    name: Mapped[str] = mapped_column(String(150))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    lead_value: Mapped[int]
    lead_unit: Mapped[str] = mapped_column(String(10))
    recipient_ids: Mapped[list[str]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True)


class Notification(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("rule_id", "document_id", "expiry_date", "recipient_id"),)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contract_alert_rules.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employee_documents.id"))
    expiry_date: Mapped[date] = mapped_column(Date)
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordSetup(UUIDMixin, OrganizationMixin, Base):
    __tablename__ = "password_setups"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailDelivery(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "email_deliveries"
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))

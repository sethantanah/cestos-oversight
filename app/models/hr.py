"""HR compensation, reminders and employee account lifecycle."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
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


class NotificationSchedule(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    __tablename__ = "notification_schedules"
    title: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(50))  # PROJECTS, WORKFORCE, EQUIPMENT, INVENTORY
    rule_type: Mapped[str] = mapped_column(String(50))  # e.g., INVENTORY_CONSUMABLES_EXPIRY, INVENTORY_LOW_STOCK, WORKFORCE_DOCUMENT_EXPIRY, EQUIPMENT_MAINTENANCE_DUE, EQUIPMENT_STATUS_CHANGE, PROJECT_MILESTONE_DUE
    lead_time_days: Mapped[int] = mapped_column(default=14)
    frequency: Mapped[str] = mapped_column(String(20), default="DAILY")  # ONCE, DAILY, EVERY_OTHER_DAY, WEEKLY, BIWEEKLY, MONTHLY
    priority_tag: Mapped[str] = mapped_column(String(20), default="IMPORTANT")  # NORMAL, IMPORTANT, CRITICAL
    delivery_method: Mapped[str] = mapped_column(String(20), default="BOTH")  # ON_PLATFORM, EMAIL, BOTH
    recipient_user_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    recipient_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class Notification(UUIDMixin, TimestampMixin, OrganizationMixin, Base):
    """Shared inbox for scheduled alerts and arbitrary domain events.

    Document-expiry producers alone populate rule_id, document_id and expiry_date.
    Their unique constraint preserves legacy deduplication. Other producers may
    omit them and use deterministic notification IDs to deduplicate events.
    schedule_id is also optional for immediate events and forwarded alerts.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("rule_id", "document_id", "expiry_date", "recipient_id"),
        Index("ix_notifications_inbox", "organization_id", "recipient_id", "created_at", "id"),
        Index("ix_notifications_unread", "organization_id", "recipient_id", "read_at"),
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_alert_rules.id"), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_documents.id"), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(1000))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), default="WORKFORCE")
    priority_tag: Mapped[str] = mapped_column(String(20), default="IMPORTANT")
    delivery_method: Mapped[str] = mapped_column(String(20), default="BOTH")
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_schedules.id"), nullable=True)
    is_resolved: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    forwarded_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    forwarded_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    forwarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forward_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)


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

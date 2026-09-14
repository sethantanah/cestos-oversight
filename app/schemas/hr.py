import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr, model_validator

from app.schemas.common import ORMModel


class SalaryCreate(BaseModel):
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    pay_period: Literal["HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL"] = "MONTHLY"
    start_date: date
    end_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def dates(self) -> "SalaryCreate":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must follow start date")
        return self


class SalaryRead(SalaryCreate, ORMModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str | None = None
    employee_number: str | None = None


class SalaryEnd(BaseModel):
    end_date: date


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    employee_id: uuid.UUID | None = None
    lead_value: int = Field(default=1, ge=0, le=3650)
    lead_unit: Literal["DAYS", "WEEKS", "MONTHS"] = "MONTHS"
    recipient_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    is_active: bool = True


class AlertRuleRead(AlertRuleCreate, ORMModel):
    id: uuid.UUID


class AccountEmail(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: SecretStr = Field(min_length=32, max_length=200)
    password: SecretStr = Field(min_length=12, max_length=128)


class SelfProfileUpdate(BaseModel):
    """Strict allowlist: email/login identity and all HR/operational fields are excluded."""

    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    preferred_name: str | None = Field(default=None, min_length=1, max_length=100)
    primary_phone: str | None = Field(default=None, min_length=1, max_length=50)
    secondary_phone: str | None = Field(default=None, min_length=1, max_length=50)
    residential_address: str | None = Field(default=None, min_length=1, max_length=1000)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    county_or_region: str | None = Field(default=None, min_length=1, max_length=100)
    country: str | None = Field(default=None, min_length=1, max_length=100)


class SelfEmergencyContact(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    full_name: str = Field(min_length=1, max_length=200)
    relationship: str = Field(min_length=1, max_length=100)
    primary_phone: str = Field(min_length=1, max_length=50)
    address: str = Field(min_length=1, max_length=1000)
    secondary_phone: str | None = Field(default=None, min_length=1, max_length=50)
    email: EmailStr | None = None


class NotificationScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain: Literal["PROJECTS", "WORKFORCE", "EQUIPMENT", "INVENTORY"] = "INVENTORY"
    rule_type: str = Field(min_length=1, max_length=100)
    lead_time_days: int = Field(default=14, ge=0, le=365)
    frequency: Literal["ONCE", "DAILY", "EVERY_OTHER_DAY", "WEEKLY", "BIWEEKLY", "MONTHLY"] = "DAILY"
    priority_tag: Literal["NORMAL", "IMPORTANT", "CRITICAL"] = "IMPORTANT"
    delivery_method: Literal["ON_PLATFORM", "EMAIL", "BOTH"] = "BOTH"
    recipient_user_ids: list[uuid.UUID] = Field(default_factory=list)
    recipient_roles: list[str] = Field(default_factory=list)
    is_active: bool = True


class NotificationScheduleUpdate(BaseModel):
    title: str | None = None
    domain: Literal["PROJECTS", "WORKFORCE", "EQUIPMENT", "INVENTORY"] | None = None
    rule_type: str | None = None
    lead_time_days: int | None = None
    frequency: Literal["ONCE", "DAILY", "EVERY_OTHER_DAY", "WEEKLY", "BIWEEKLY", "MONTHLY"] | None = None
    priority_tag: Literal["NORMAL", "IMPORTANT", "CRITICAL"] | None = None
    delivery_method: Literal["ON_PLATFORM", "EMAIL", "BOTH"] | None = None
    recipient_user_ids: list[uuid.UUID] | None = None
    recipient_roles: list[str] | None = None
    is_active: bool | None = None


class NotificationScheduleRead(NotificationScheduleCreate, ORMModel):
    id: uuid.UUID


class NotificationForwardRequest(BaseModel):
    target_user_id: uuid.UUID | None = None
    target_user_ids: list[uuid.UUID] | None = None
    notes: str | None = Field(default=None, max_length=1000)

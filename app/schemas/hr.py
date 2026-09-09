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

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.schemas.common import ORMModel

PORTAL_TYPES = ("FULL", "FIELD", "HR", "FINANCE", "FIELD_ADMIN", "EXECUTIVE")


class PermissionRead(ORMModel):
    id: uuid.UUID
    code: str
    description: str | None = None


class RoleRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_system_role: bool = False
    permissions: list[PermissionRead] = []


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdatePermissions(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)


class UserRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    is_active: bool
    is_superuser: bool
    is_field_portal_only: bool = False
    portal_type: str = "FULL"
    setup_required: bool = False
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleRead] = []


class UserCreate(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    is_field_portal_only: bool = False
    portal_type: str = "FULL"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("portal_type")
    @classmethod
    def validate_portal_type(cls, value: str) -> str:
        if value not in PORTAL_TYPES:
            raise ValueError(f"portal_type must be one of {PORTAL_TYPES}")
        return value


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    is_field_portal_only: bool | None = None
    portal_type: str | None = None
    role_ids: list[uuid.UUID] | None = None

    @field_validator("portal_type")
    @classmethod
    def validate_portal_type(cls, value: str | None) -> str | None:
        if value is not None and value not in PORTAL_TYPES:
            raise ValueError(f"portal_type must be one of {PORTAL_TYPES}")
        return value

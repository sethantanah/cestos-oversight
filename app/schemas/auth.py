import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    organization_id: uuid.UUID
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=32, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AccessResponse(BaseModel):
    roles: list[str]
    permissions: list[str]
    is_superuser: bool

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=300)
    primary_contact_name: str | None = Field(default=None, max_length=150)
    primary_contact_email: str | None = Field(default=None, max_length=320)
    primary_contact_phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    billing_email: str | None = Field(default=None, max_length=320)
    notes: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=300)
    primary_contact_name: str | None = Field(default=None, max_length=150)
    primary_contact_email: str | None = Field(default=None, max_length=320)
    primary_contact_phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    billing_email: str | None = Field(default=None, max_length=320)
    notes: str | None = None
    is_active: bool | None = None


class ClientRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    client_number: str
    name: str
    legal_name: str | None
    primary_contact_name: str | None
    primary_contact_email: str | None
    primary_contact_phone: str | None
    address: str | None
    country: str | None
    billing_email: str | None
    notes: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


ClientListItem = ClientRead

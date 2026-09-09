import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.location import LocationType
from app.schemas.common import ORMModel


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location_type: LocationType = LocationType.OTHER
    project_id: uuid.UUID | None = None
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    county_or_region: str | None = Field(default=None, max_length=100)
    country: str = Field(default="LR", min_length=2, max_length=2)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_type: LocationType | None = None
    project_id: uuid.UUID | None = None
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    county_or_region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    is_active: bool | None = None


class LocationRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    location_number: str
    name: str
    location_type: LocationType
    project_id: uuid.UUID | None
    address: str | None
    city: str | None
    county_or_region: str | None
    country: str
    latitude: float | None
    longitude: float | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


LocationListItem = LocationRead

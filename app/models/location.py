import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Index, String
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class LocationType(enum.StrEnum):
    HEAD_OFFICE = "HEAD_OFFICE"
    WORKSHOP = "WORKSHOP"
    WAREHOUSE = "WAREHOUSE"
    PROJECT_SITE = "PROJECT_SITE"
    YARD = "YARD"
    FUEL_STORAGE = "FUEL_STORAGE"
    OTHER = "OTHER"


class Location(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (
        Index("ix_locations_org_number", "organization_id", "location_number", unique=True),
        Index("ix_locations_org_project", "organization_id", "project_id"),
        Index("ix_locations_org_type", "organization_id", "location_type"),
    )

    location_number: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    location_type: Mapped[LocationType] = mapped_column(
        Enum(LocationType, name="location_type"), default=LocationType.OTHER
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    address: Mapped[str | None] = mapped_column(SAText)
    city: Mapped[str | None] = mapped_column(String(100))
    county_or_region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="LR")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(SAText)

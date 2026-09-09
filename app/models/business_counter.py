from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import OrganizationMixin, TimestampMixin, UUIDMixin


class BusinessCounter(UUIDMixin, OrganizationMixin, TimestampMixin, Base):
    """Organization-scoped monotonic counters for readable business identifiers.

    entity_type examples: employee, client, project, location, assignment,
    asset, asset_category (no public number), future: work_order, purchase_order.
    """

    __tablename__ = "business_counters"
    __table_args__ = (UniqueConstraint("organization_id", "entity_type"),)

    entity_type: Mapped[str] = mapped_column(String(50))
    current_value: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

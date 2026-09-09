import uuid

from sqlalchemy import Select, select

from app.db.base import Base
from app.db.mixins import OrganizationMixin


def organization_query[T: Base](model: type[T], organization_id: uuid.UUID) -> Select[tuple[T]]:
    """Mandatory starting point for organization-owned record reads."""
    if not issubclass(model, OrganizationMixin):
        raise TypeError("Model must have an organization boundary")
    return select(model).where(model.organization_id == organization_id)

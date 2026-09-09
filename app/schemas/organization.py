import uuid

from app.schemas.common import ORMModel


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    legal_name: str | None
    country: str
    default_currency: str
    timezone: str
    is_active: bool

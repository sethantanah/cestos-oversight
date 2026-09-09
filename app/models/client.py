from sqlalchemy import Index, String
from sqlalchemy import Text as SAText
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ActorMixin, ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin


class Client(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, ActorMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_org_number", "organization_id", "client_number", unique=True),
    )

    client_number: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(300))
    primary_contact_name: Mapped[str | None] = mapped_column(String(150))
    primary_contact_email: Mapped[str | None] = mapped_column(String(320))
    primary_contact_phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(SAText)
    country: Mapped[str | None] = mapped_column(String(2))
    billing_email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(SAText)

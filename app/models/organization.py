from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import ArchiveMixin, TimestampMixin, UUIDMixin


class Organization(UUIDMixin, TimestampMixin, ArchiveMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint("length(default_currency) = 3", name="currency_length"),)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2), default="LR")
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(100), default="Africa/Monrovia")

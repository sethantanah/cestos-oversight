import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import ArchiveMixin, OrganizationMixin, TimestampMixin, UUIDMixin
from app.models.role import Role


class User(UUIDMixin, TimestampMixin, OrganizationMixin, ArchiveMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    is_superuser: Mapped[bool] = mapped_column(default=False, server_default="false")
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")
    setup_required: Mapped[bool] = mapped_column(default=False, server_default="false")
    supabase_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="raise")


class RefreshToken(UUIDMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(45))

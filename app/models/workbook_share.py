"""Revocable workbook snapshots with explicit editor grants and optimistic revisions."""
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.db.mixins import UUIDMixin, OrganizationMixin, TimestampMixin

class WorkbookShare(UUIDMixin, OrganizationMixin, TimestampMixin, Base):
    __tablename__ = "workbook_shares"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    workbook_id: Mapped[str] = mapped_column(String(100), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    workbook: Mapped[dict] = mapped_column(JSONB)
    editor_ids: Mapped[list] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(default=1)
    history: Mapped[list] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)

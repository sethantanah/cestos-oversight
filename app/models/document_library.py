"""Organization document catalog; source files keep their existing record IDs."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import OrganizationMixin, TimestampMixin, UUIDMixin


class LibraryDocument(UUIDMixin, OrganizationMixin, TimestampMixin, Base):
    __tablename__ = "library_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_type", "source_id", name="uq_library_source"),
        CheckConstraint(
            "visibility IN ('PRIVATE','PUBLIC','SUPER_PRIVATE')", name="library_visibility"
        ),
        CheckConstraint(
            "visibility != 'SUPER_PRIVATE' OR private_to_id IS NOT NULL",
            name="library_private_holder",
        ),
        Index("ix_library_category", "organization_id", "category"),
        Index("ix_library_owner", "organization_id", "owner_id"),
        Index("ix_library_pending", "index_status"),
        Index("ix_library_tags", "tags", postgresql_using="gin"),
    )
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(250))
    category: Mapped[str] = mapped_column(String(60), default="General")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    storage_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(150), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(default=0)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    visibility: Mapped[str] = mapped_column(String(20), default="PRIVATE")
    private_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    index_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    index_message: Mapped[str | None] = mapped_column(String(500))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    chunks: Mapped[list] = mapped_column(JSONB, default=list)
    vector_path: Mapped[str | None] = mapped_column(Text)

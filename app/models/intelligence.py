import uuid
from typing import Any
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import OrganizationMixin, TimestampMixin, UUIDMixin


class AssistantChatMessage(UUIDMixin, OrganizationMixin, TimestampMixin, Base):
    __tablename__ = "assistant_chat_messages"
    __table_args__ = (
        Index("ix_assistant_chats_org_user", "organization_id", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, default=list)
    tools_used: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    suggested_filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)

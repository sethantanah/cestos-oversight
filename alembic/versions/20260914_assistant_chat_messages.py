"""Add assistant_chat_messages table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "20260914_assistant_chat_messages"
down_revision = "20260913_notifications_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("tools_used", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("suggested_filters", postgresql.JSONB(), server_default="{}", nullable=True),
    )
    op.create_index("ix_assistant_chat_messages_user_id", "assistant_chat_messages", ["user_id"])
    op.create_index(
        "ix_assistant_chats_org_user",
        "assistant_chat_messages",
        ["organization_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_chats_org_user", table_name="assistant_chat_messages")
    op.drop_index("ix_assistant_chat_messages_user_id", table_name="assistant_chat_messages")
    op.drop_table("assistant_chat_messages")

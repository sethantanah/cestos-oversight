"""Add notification_schedules table and extension columns to notifications table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "20260913_notifications_system"
down_revision = "20260913_document_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create notification_schedules table
    op.create_table(
        "notification_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("frequency", sa.String(20), server_default="DAILY", nullable=False),
        sa.Column("priority_tag", sa.String(20), server_default="IMPORTANT", nullable=False),
        sa.Column("delivery_method", sa.String(20), server_default="BOTH", nullable=False),
        sa.Column("recipient_user_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("recipient_roles", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
    )

    # 2. Add new columns to notifications table
    op.add_column(
        "notifications",
        sa.Column("domain", sa.String(50), server_default="WORKFORCE", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("priority_tag", sa.String(20), server_default="IMPORTANT", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("delivery_method", sa.String(20), server_default="BOTH", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "schedule_id", sa.Uuid(), sa.ForeignKey("notification_schedules.id"), nullable=True
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("is_resolved", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("resolved_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("forwarded_from_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("forwarded_to_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("forward_notes", sa.String(1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "forward_notes")
    op.drop_column("notifications", "forwarded_at")
    op.drop_column("notifications", "forwarded_to_id")
    op.drop_column("notifications", "forwarded_from_id")
    op.drop_column("notifications", "resolved_by_id")
    op.drop_column("notifications", "resolved_at")
    op.drop_column("notifications", "is_resolved")
    op.drop_column("notifications", "schedule_id")
    op.drop_column("notifications", "delivery_method")
    op.drop_column("notifications", "priority_tag")
    op.drop_column("notifications", "domain")
    op.drop_table("notification_schedules")

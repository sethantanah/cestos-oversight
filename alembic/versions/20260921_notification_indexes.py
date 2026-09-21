"""Index recipient inbox pagination and unread badge counts."""

from alembic import op

revision = "20260921_notification_indexes"
down_revision = "20260921_merge_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Concurrent indexes avoid blocking notification writers during deployment.
    # IF NOT EXISTS also permits retry after a partially completed migration.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_notifications_inbox", "notifications",
            ["organization_id", "recipient_id", "created_at", "id"],
            postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            "ix_notifications_unread", "notifications",
            ["organization_id", "recipient_id", "read_at"],
            postgresql_concurrently=True, if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_notifications_unread", postgresql_concurrently=True, if_exists=True)
        op.drop_index("ix_notifications_inbox", postgresql_concurrently=True, if_exists=True)

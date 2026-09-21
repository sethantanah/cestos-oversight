"""Repair document-only constraints on the shared notifications table.

Reapply the intended schema in a new revision for deployments with legacy
constraints. Preserve document expiry foreign keys and deduplication.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_notification_optional"
down_revision = "20260920_field_work_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type in (
        ("rule_id", sa.Uuid()),
        ("document_id", sa.Uuid()),
        ("expiry_date", sa.Date()),
    ):
        op.alter_column("notifications", name, existing_type=column_type, nullable=True)
    op.alter_column(
        "notifications", "message", existing_type=sa.String(500),
        type_=sa.String(1000), existing_nullable=False,
    )


def downgrade() -> None:
    # Earlier revisions already intend nullable fields and 1000-character
    # messages. Keep that schema instead of restoring drift and breaking valid
    # non-document notifications.
    pass

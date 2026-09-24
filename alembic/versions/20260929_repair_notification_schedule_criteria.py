"""Repair notification criteria when a deployment stamped the earlier revision without the column."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260929_notif_criteria"
down_revision = "20260928_finance_alert_criteria"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("notification_schedules"):
        raise RuntimeError("notification_schedules is missing; apply the notification-system migrations first")
    columns = {column["name"] for column in inspector.get_columns("notification_schedules")}
    if "criteria" not in columns:
        op.add_column(
            "notification_schedules",
            sa.Column(
                "criteria",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    # Keep the repaired column: the preceding revision owns it and older DBs
    # may have received it through a manual schema repair.
    pass

"""Add criteria payloads to notification schedules for event thresholds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260928_finance_alert_criteria"
down_revision = "20260927_po_approval_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("notification_schedules"):
        raise RuntimeError("notification_schedules must exist before adding its criteria column")
    if "criteria" not in {column["name"] for column in inspector.get_columns("notification_schedules")}:
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
    op.drop_column("notification_schedules", "criteria")

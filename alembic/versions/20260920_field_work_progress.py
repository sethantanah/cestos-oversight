"""Persist field checklists, notes, and supervisor approval."""

from alembic import op
import sqlalchemy as sa

revision = "20260920_field_work_progress"
down_revision = "20260919_user_field_portal"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("asset_maintenance_jobs", "maintenance_work_orders"):
        op.add_column(table, sa.Column("checklist", sa.JSON(), nullable=False, server_default="[]"))
        op.add_column(table, sa.Column("field_notes", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table, sa.Column("approved_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True)
        )


def downgrade():
    for table in ("maintenance_work_orders", "asset_maintenance_jobs"):
        for name in ("approved_by_id", "approved_at", "field_notes", "checklist"):
            op.drop_column(table, name)

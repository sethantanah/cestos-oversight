"""Add recurring maintenance and assigned employee columns to asset_maintenance_jobs table."""

import sqlalchemy as sa
from alembic import op

revision = "20260913_maint_recurring"
down_revision = "20260912_position_supervisory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_maintenance_jobs",
        sa.Column("assigned_employee_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_asset_maintenance_jobs_assigned_employee_id",
        "asset_maintenance_jobs",
        "employees",
        ["assigned_employee_id"],
        ["id"],
    )
    op.add_column(
        "asset_maintenance_jobs",
        sa.Column("is_recurring", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "asset_maintenance_jobs",
        sa.Column("recurrence_interval_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_asset_maintenance_jobs_assigned_employee_id",
        "asset_maintenance_jobs",
        type_="foreignkey",
    )
    op.drop_column("asset_maintenance_jobs", "recurrence_interval_days")
    op.drop_column("asset_maintenance_jobs", "is_recurring")
    op.drop_column("asset_maintenance_jobs", "assigned_employee_id")

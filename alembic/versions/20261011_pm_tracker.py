"""Add preventive maintenance tracker.

Revision ID: 20261011_pm_tracker
Revises: 20261010_action_tracker
"""

from alembic import op
import sqlalchemy as sa

revision = "20261011_pm_tracker"
down_revision = "20261010_action_tracker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pm_trackers",
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("equipment", sa.String(300), nullable=False),
        sa.Column("service_type", sa.String(200), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("planned_actual", sa.String(20), server_default="PLANNED", nullable=False),
        sa.Column("pm_completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("defects_found", sa.Text(), nullable=True),
        sa.Column("parts_required", sa.Text(), nullable=True),
        sa.Column("technician_employee_id", sa.Uuid(), nullable=True),
        sa.Column("technician_name", sa.String(200), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["technician_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pm_trackers_project_id", "pm_trackers", ["project_id"])
    op.create_index("ix_pm_trackers_org_project_due", "pm_trackers", ["organization_id", "project_id", "due_date"])


def downgrade() -> None:
    op.drop_index("ix_pm_trackers_org_project_due", table_name="pm_trackers")
    op.drop_index("ix_pm_trackers_project_id", table_name="pm_trackers")
    op.drop_table("pm_trackers")

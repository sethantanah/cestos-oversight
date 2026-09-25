"""Add project action tracker records.

Revision ID: 20261010_action_tracker
Revises: 20261009_drop_assess_site
"""

from alembic import op
import sqlalchemy as sa

revision = "20261010_action_tracker"
down_revision = "20261009_drop_assess_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_trackers",
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("equipment_area", sa.String(300), nullable=False),
        sa.Column("issue_finding", sa.Text(), nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column("parts_required", sa.Text(), nullable=True),
        sa.Column("responsible_employee_id", sa.Uuid(), nullable=True),
        sa.Column("responsible_name", sa.String(200), nullable=True),
        sa.Column("priority", sa.String(30), server_default="MEDIUM", nullable=False),
        sa.Column("status", sa.String(30), server_default="OPEN", nullable=False),
        sa.Column("completion_date", sa.Date(), nullable=True),
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
        sa.ForeignKeyConstraint(["responsible_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_trackers_project_id", "action_trackers", ["project_id"])
    op.create_index("ix_action_trackers_org_project_date", "action_trackers", ["organization_id", "project_id", "action_date"])


def downgrade() -> None:
    op.drop_index("ix_action_trackers_org_project_date", table_name="action_trackers")
    op.drop_index("ix_action_trackers_project_id", table_name="action_trackers")
    op.drop_table("action_trackers")

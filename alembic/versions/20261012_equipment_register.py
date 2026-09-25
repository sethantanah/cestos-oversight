"""Add project equipment register entries.

Revision ID: 20261012_equipment_register
Revises: 20261011_pm_tracker
"""

from alembic import op
import sqlalchemy as sa

revision = "20261012_equipment_register"
down_revision = "20261011_pm_tracker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_register_entries",
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("equipment", sa.String(300), nullable=False),
        sa.Column("unit_number", sa.String(100), nullable=True),
        sa.Column("equipment_type", sa.String(200), nullable=True),
        sa.Column("status", sa.String(100), server_default="Operational / Monitoring", nullable=False),
        sa.Column("open_defects", sa.Text(), nullable=True),
        sa.Column("action_required", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(30), server_default="MEDIUM", nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_register_entries_project_id", "equipment_register_entries", ["project_id"])
    op.create_index("ix_equipment_register_org_project", "equipment_register_entries", ["organization_id", "project_id"])


def downgrade() -> None:
    op.drop_index("ix_equipment_register_org_project", table_name="equipment_register_entries")
    op.drop_index("ix_equipment_register_entries_project_id", table_name="equipment_register_entries")
    op.drop_table("equipment_register_entries")

"""Allow PM job cards to record equipment not yet in the asset register.

Revision ID: 20260922_pm_equipment_optional
Revises: 20260923_merge_expenses_portal
"""

from alembic import op
import sqlalchemy as sa

revision = "20260922_pm_equipment_optional"
down_revision = "20260923_merge_expenses_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pm_job_cards", "asset_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.alter_column("pm_job_cards", "asset_id", existing_type=sa.Uuid(), nullable=False)

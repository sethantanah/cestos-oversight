"""Add category column to operational_expenses table.

Revision ID: 20261021_opex_category
Revises: 20261020_supplier_profile
"""

from alembic import op


revision = "20261021_opex_category"
down_revision = "20261020_supplier_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE operational_expenses ADD COLUMN IF NOT EXISTS category VARCHAR(100)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE operational_expenses DROP COLUMN IF EXISTS category")

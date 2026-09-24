"""add_fuel_deliveries_defaults

Revision ID: 75e8488bdd02
Revises: 20260922_merge_pm_docs
"""
from alembic import op
import sqlalchemy as sa

revision = '75e8488bdd02'
down_revision = '20260922_merge_pm_docs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('fuel_deliveries', 'created_at', server_default=sa.func.now())
    op.alter_column('fuel_deliveries', 'updated_at', server_default=sa.func.now())
    op.alter_column('fuel_allocations', 'created_at', server_default=sa.func.now())
    op.alter_column('fuel_allocations', 'updated_at', server_default=sa.func.now())


def downgrade() -> None:
    op.alter_column('fuel_deliveries', 'created_at', server_default=None)
    op.alter_column('fuel_deliveries', 'updated_at', server_default=None)
    op.alter_column('fuel_allocations', 'created_at', server_default=None)
    op.alter_column('fuel_allocations', 'updated_at', server_default=None)

"""Make purchase order item description nullable.

Revision ID: 20261016_po_desc_nullable
Revises: 20261016_data_change_feed
"""

from alembic import op
import sqlalchemy as sa


revision = "20261016_po_desc_nullable"
down_revision = "20261016_data_change_feed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(128)")
    op.alter_column(
        "purchase_order_items",
        "description",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "purchase_order_items",
        "description",
        existing_type=sa.String(length=255),
        nullable=False,
    )

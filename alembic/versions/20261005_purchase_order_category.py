"""Add optional categories to purchase orders."""

from alembic import op
import sqlalchemy as sa


revision = "20261005_po_category"
down_revision = "20261004_fuel_delivery_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("purchase_orders"):
        columns = {column["name"] for column in inspector.get_columns("purchase_orders")}
        if "category" not in columns:
            op.add_column("purchase_orders", sa.Column("category", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("purchase_orders"):
        columns = {column["name"] for column in inspector.get_columns("purchase_orders")}
        if "category" in columns:
            op.drop_column("purchase_orders", "category")

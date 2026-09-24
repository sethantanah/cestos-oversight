"""Add purchase order approval audit and attachment metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_po_approval_files"
down_revision = "20260926_repair_pm_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("attachment_path", sa.Text(), nullable=True))
    op.add_column("purchase_orders", sa.Column("attachment_file_name", sa.String(255), nullable=True))
    op.add_column("purchase_orders", sa.Column("attachment_mime_type", sa.String(150), nullable=True))
    op.add_column("purchase_orders", sa.Column("attachment_size_bytes", sa.Integer(), nullable=True))
    op.add_column("purchase_orders", sa.Column("approved_by_id", sa.Uuid(), nullable=True))
    op.add_column("purchase_orders", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_purchase_orders_approved_by_id_users",
        "purchase_orders",
        "users",
        ["approved_by_id"],
        ["id"],
    )
    op.add_column("purchase_order_items", sa.Column("item_name", sa.String(200), nullable=True))
    op.execute("UPDATE purchase_order_items SET item_name = description WHERE item_name IS NULL")


def downgrade() -> None:
    op.drop_column("purchase_order_items", "item_name")
    op.drop_constraint("fk_purchase_orders_approved_by_id_users", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "approved_at")
    op.drop_column("purchase_orders", "approved_by_id")
    op.drop_column("purchase_orders", "attachment_size_bytes")
    op.drop_column("purchase_orders", "attachment_mime_type")
    op.drop_column("purchase_orders", "attachment_file_name")
    op.drop_column("purchase_orders", "attachment_path")

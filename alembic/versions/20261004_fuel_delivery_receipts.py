"""Persist fuel delivery receipt and docket uploads."""

from alembic import op
import sqlalchemy as sa


revision = "20261004_fuel_delivery_receipts"
down_revision = "20261003_expense_payment_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fuel_deliveries", sa.Column("receipt_path", sa.Text(), nullable=True))
    op.add_column("fuel_deliveries", sa.Column("receipt_file_name", sa.String(length=255), nullable=True))
    op.add_column("fuel_deliveries", sa.Column("receipt_mime_type", sa.String(length=150), nullable=True))
    op.add_column("fuel_deliveries", sa.Column("receipt_size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fuel_deliveries", "receipt_size_bytes")
    op.drop_column("fuel_deliveries", "receipt_mime_type")
    op.drop_column("fuel_deliveries", "receipt_file_name")
    op.drop_column("fuel_deliveries", "receipt_path")

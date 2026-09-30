"""Add supplier account details for the Finance vendor master.

Revision ID: 20261019_vendor_master
Revises: 20261018_exp_status_fix
"""

from alembic import op
import sqlalchemy as sa


revision = "20261019_vendor_master"
down_revision = "20261018_exp_status_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("supplier_number", sa.String(50), nullable=True))
    op.add_column("suppliers", sa.Column("bank_account_type", sa.String(40), nullable=True))
    op.add_column("suppliers", sa.Column("payment_method", sa.String(40), nullable=True))
    op.add_column("suppliers", sa.Column("bank_account_details", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_suppliers_org_supplier_number", "suppliers", ["organization_id", "supplier_number"]
    )
    op.add_column("operational_payees", sa.Column("payment_method", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("operational_payees", "payment_method")
    op.drop_constraint("uq_suppliers_org_supplier_number", "suppliers", type_="unique")
    op.drop_column("suppliers", "bank_account_details")
    op.drop_column("suppliers", "payment_method")
    op.drop_column("suppliers", "bank_account_type")
    op.drop_column("suppliers", "supplier_number")

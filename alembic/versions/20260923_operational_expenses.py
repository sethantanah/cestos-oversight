"""Add operational expense and saved payee workflows."""
from alembic import op
import sqlalchemy as sa

revision = "20260923_operational_expenses"
down_revision = "20260922_pm_job_cards"
branch_labels = None
depends_on = None

def common():
    return [sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("archived_at", sa.DateTime(timezone=True))]

def upgrade():
    op.create_table("operational_payees", *common(), sa.Column("name", sa.String(200), nullable=False), sa.Column("phone", sa.String(50)), sa.Column("bank_account_details", sa.Text()))
    op.create_table("operational_expenses", *common(), sa.Column("expense_number", sa.String(50), nullable=False, unique=True), sa.Column("submitted_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("payee_id", sa.Uuid(), sa.ForeignKey("operational_payees.id")), sa.Column("pay_to_name", sa.String(200), nullable=False), sa.Column("pay_to_phone", sa.String(50)), sa.Column("bank_account_details", sa.Text()), sa.Column("expense_date", sa.Date(), nullable=False), sa.Column("payment_method", sa.String(40), nullable=False), sa.Column("items", sa.JSON(), nullable=False, server_default="[]"), sa.Column("total_cost", sa.Numeric(18, 2), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="SUBMITTED"), sa.Column("invoice_path", sa.Text()), sa.Column("invoice_name", sa.String(255)), sa.Column("invoice_mime_type", sa.String(150)), sa.Column("invoice_size_bytes", sa.Integer()), sa.Column("receipt_path", sa.Text()), sa.Column("receipt_name", sa.String(255)), sa.Column("receipt_mime_type", sa.String(150)), sa.Column("receipt_size_bytes", sa.Integer()), sa.Column("paid_by_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("paid_at", sa.DateTime(timezone=True)), sa.Column("extraction_status", sa.String(20), nullable=False, server_default="PENDING"), sa.Column("extracted_data", sa.JSON(), nullable=False, server_default="{}"))
    op.create_index("ix_operational_expenses_submitted_by_id", "operational_expenses", ["submitted_by_id"])
    op.create_index("ix_operational_expenses_status", "operational_expenses", ["status"])

def downgrade():
    op.drop_table("operational_expenses")
    op.drop_table("operational_payees")

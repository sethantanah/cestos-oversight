"""Track multiple partial disbursements for operational expenses."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_expense_payments"
down_revision = "20261001_email_kind_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_expense_payments",
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("receipt_path", sa.Text(), nullable=False),
        sa.Column("receipt_name", sa.String(255), nullable=False),
        sa.Column("receipt_mime_type", sa.String(150), nullable=True),
        sa.Column("receipt_size_bytes", sa.Integer(), nullable=True),
        sa.Column("paid_by_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["expense_id"], ["operational_expenses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paid_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.CheckConstraint("amount > 0", name="operational_expense_payment_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operational_expense_payments_expense_id", "operational_expense_payments", ["expense_id"])
    op.create_index("ix_operational_expense_payment_expense", "operational_expense_payments", ["organization_id", "expense_id", "payment_date"])


def downgrade() -> None:
    op.drop_index("ix_operational_expense_payment_expense", table_name="operational_expense_payments")
    op.drop_index("ix_operational_expense_payments_expense_id", table_name="operational_expense_payments")
    op.drop_table("operational_expense_payments")

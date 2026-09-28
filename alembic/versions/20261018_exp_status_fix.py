"""Reset partial-payment labels that have no recorded payment installments."""

from alembic import op
import sqlalchemy as sa


revision = "20261018_exp_status_fix"
down_revision = "20261017_repair_change_feed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("operational_expenses") or not inspector.has_table(
        "operational_expense_payments"
    ):
        return

    op.execute(sa.text("""
        UPDATE operational_expenses AS expense
        SET status = 'SUBMITTED'
        WHERE UPPER(expense.status) = 'PARTIALLY_PAID'
          AND NOT EXISTS (
              SELECT 1
              FROM operational_expense_payments AS payment
              WHERE payment.expense_id = expense.id
                AND payment.organization_id = expense.organization_id
          )
    """))


def downgrade() -> None:
    # A corrected payment status cannot be safely reconstructed on downgrade.
    pass

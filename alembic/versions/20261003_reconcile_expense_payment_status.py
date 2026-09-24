"""Reconcile expense statuses against recorded payments."""

from alembic import op
import sqlalchemy as sa

revision = "20261003_expense_payment_status"
down_revision = "20261002_expense_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("operational_expenses") or not inspector.has_table("operational_expense_payments"):
        return

    # Derive status from payment totals. A legacy completion without payment
    # rows is treated as having its full balance outstanding; keep a separate
    # API flag for the missing historical payment record.
    op.execute(sa.text("""
        UPDATE operational_expenses AS expense
        SET status = CASE
            WHEN COALESCE(payments.paid_amount, 0) >= expense.total_cost THEN 'COMPLETED'
            ELSE 'PARTIALLY_PAID'
        END
        FROM (
            SELECT target.id AS expense_id, SUM(payment.amount) AS paid_amount
            FROM operational_expenses AS target
            LEFT JOIN operational_expense_payments AS payment
                ON payment.expense_id = target.id
               AND payment.organization_id = target.organization_id
            WHERE UPPER(target.status) IN ('PAID', 'COMPLETED', 'PARTIALLY_PAID')
            GROUP BY target.id
        ) AS payments
        WHERE expense.id = payments.expense_id
          AND UPPER(expense.status) IN ('PAID', 'COMPLETED', 'PARTIALLY_PAID')
    """))

    # Enforce the payment invariant in PostgreSQL as well as in the API. The
    # deferred check allows the API to insert a payment and update the expense
    # status in the same transaction, then validates the final transaction
    # state before commit.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION enforce_operational_expense_paid_balance()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            expense_ids uuid[];
            target_id uuid;
            target_total numeric(18, 2);
            target_status varchar(30);
            recorded_paid numeric(18, 2);
        BEGIN
            IF TG_TABLE_NAME = 'operational_expenses' THEN
                IF TG_OP = 'DELETE' THEN
                    expense_ids := ARRAY[OLD.id];
                ELSE
                    expense_ids := ARRAY[NEW.id];
                END IF;
            ELSIF TG_OP = 'INSERT' THEN
                expense_ids := ARRAY[NEW.expense_id];
            ELSIF TG_OP = 'DELETE' THEN
                expense_ids := ARRAY[OLD.expense_id];
            ELSE
                expense_ids := ARRAY[OLD.expense_id, NEW.expense_id];
            END IF;

            FOREACH target_id IN ARRAY expense_ids LOOP
                SELECT status, total_cost INTO target_status, target_total
                FROM operational_expenses WHERE id = target_id;
                IF NOT FOUND OR UPPER(COALESCE(target_status, '')) <> 'COMPLETED' THEN
                    CONTINUE;
                END IF;

                SELECT COALESCE(SUM(amount), 0) INTO recorded_paid
                FROM operational_expense_payments
                WHERE expense_id = target_id;

                IF recorded_paid < target_total THEN
                    RAISE EXCEPTION 'Operational expense % cannot be completed: paid % is below total %',
                        target_id, recorded_paid, target_total
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            RETURN NULL;
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER operational_expense_paid_balance_check
        AFTER INSERT OR UPDATE OR DELETE ON operational_expenses
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_operational_expense_paid_balance()
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER operational_expense_payment_balance_check
        AFTER INSERT OR UPDATE OR DELETE ON operational_expense_payments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_operational_expense_paid_balance()
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS operational_expense_payment_balance_check ON operational_expense_payments"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS operational_expense_paid_balance_check ON operational_expenses"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_operational_expense_paid_balance()"))
    # Status repair is data reconciliation and cannot be safely reversed.

"""Link operational expenses to approved purchase orders."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_po_expense_link"
down_revision = "20260929_notif_criteria"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("operational_expenses") or not inspector.has_table("purchase_orders"):
        raise RuntimeError("Operational expense and purchase order tables must exist before linking them")
    columns = {column["name"] for column in inspector.get_columns("operational_expenses")}
    if "purchase_order_id" not in columns:
        op.add_column("operational_expenses", sa.Column("purchase_order_id", sa.Uuid(), nullable=True))
    foreign_keys = {constraint.get("name") for constraint in inspector.get_foreign_keys("operational_expenses")}
    if "fk_operational_expenses_purchase_order_id_purchase_orders" not in foreign_keys:
        op.create_foreign_key(
            "fk_operational_expenses_purchase_order_id_purchase_orders",
            "operational_expenses", "purchase_orders", ["purchase_order_id"], ["id"], ondelete="SET NULL",
        )
    indexes = {index["name"] for index in inspector.get_indexes("operational_expenses")}
    if "ix_operational_expenses_purchase_order_id" not in indexes:
        op.create_index("ix_operational_expenses_purchase_order_id", "operational_expenses", ["purchase_order_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("operational_expenses"):
        return
    indexes = {index["name"] for index in inspector.get_indexes("operational_expenses")}
    if "ix_operational_expenses_purchase_order_id" in indexes:
        op.drop_index("ix_operational_expenses_purchase_order_id", table_name="operational_expenses")
    foreign_keys = {constraint.get("name") for constraint in inspector.get_foreign_keys("operational_expenses")}
    if "fk_operational_expenses_purchase_order_id_purchase_orders" in foreign_keys:
        op.drop_constraint("fk_operational_expenses_purchase_order_id_purchase_orders", "operational_expenses", type_="foreignkey")
    columns = {column["name"] for column in inspector.get_columns("operational_expenses")}
    if "purchase_order_id" in columns:
        op.drop_column("operational_expenses", "purchase_order_id")

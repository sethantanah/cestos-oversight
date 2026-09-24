"""Allow longer notification kinds in queued email deliveries."""

import sqlalchemy as sa
from alembic import op

revision = "20261001_email_kind_length"
down_revision = "20260930_po_expense_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("email_deliveries"):
        return

    columns = {column["name"]: column for column in inspector.get_columns("email_deliveries")}
    kind = columns.get("kind")
    if kind is None:
        return

    current_length = getattr(kind["type"], "length", None)
    if current_length is not None and current_length < 100:
        op.alter_column(
            "email_deliveries",
            "kind",
            existing_type=sa.String(length=current_length),
            type_=sa.String(length=100),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Retain the wider column so existing event identifiers remain intact.
    pass

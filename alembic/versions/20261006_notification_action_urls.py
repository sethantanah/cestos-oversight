"""Add deep links to in-app notifications and email deliveries."""

from alembic import op
import sqlalchemy as sa


revision = "20261006_notif_action_urls"
down_revision = "20261005_po_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("notifications", "email_deliveries"):
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "action_url" not in columns:
            op.add_column(table, sa.Column("action_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("email_deliveries", "notifications"):
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "action_url" in columns:
            op.drop_column(table, "action_url")

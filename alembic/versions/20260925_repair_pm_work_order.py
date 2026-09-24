"""Repair the optional work-order link on preventive maintenance cards."""

from alembic import op
import sqlalchemy as sa


revision = "20260925_repair_pm_work_order"
down_revision = "20260924_repair_breakdown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pm_job_cards"):
        return

    columns = {column["name"] for column in inspector.get_columns("pm_job_cards")}
    if "work_order_id" not in columns:
        op.add_column(
            "pm_job_cards",
            sa.Column(
                "work_order_id",
                sa.Uuid(),
                sa.ForeignKey("maintenance_work_orders.id"),
                nullable=True,
            ),
        )

    indexes = {index["name"] for index in inspector.get_indexes("pm_job_cards")}
    if "ix_pm_job_cards_work_order_id" not in indexes:
        op.create_index("ix_pm_job_cards_work_order_id", "pm_job_cards", ["work_order_id"])


def downgrade() -> None:
    # The repair must not remove links or job-card data during downgrade.
    pass

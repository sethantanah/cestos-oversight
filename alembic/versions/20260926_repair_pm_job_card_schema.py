"""Ensure PM job card link and timestamp defaults exist on deployed databases."""

from alembic import op
import sqlalchemy as sa


revision = "20260926_repair_pm_schema"
down_revision = "20260925_repair_pm_work_order"
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
            sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("maintenance_work_orders.id"), nullable=True),
        )
    indexes = {index["name"] for index in inspector.get_indexes("pm_job_cards")}
    if "ix_pm_job_cards_work_order_id" not in indexes:
        op.create_index("ix_pm_job_cards_work_order_id", "pm_job_cards", ["work_order_id"])

    # The original PM migration declared these NOT NULL without server defaults,
    # while ORM-created records depend on defaults from the model mixin.
    for column in ("created_at", "updated_at"):
        if column in columns:
            op.alter_column(
                "pm_job_cards", column,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            )


def downgrade() -> None:
    # Preserve data and schema compatibility during rollback.
    pass

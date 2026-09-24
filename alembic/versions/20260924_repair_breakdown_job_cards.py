"""Create the breakdown job card table if an earlier migration was stamped without it."""

from alembic import op
import sqlalchemy as sa


revision = "20260924_repair_breakdown"
down_revision = "75e8488bdd02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("pm_job_cards"):
        pm_columns = {column["name"] for column in inspector.get_columns("pm_job_cards")}
        if "work_order_id" not in pm_columns:
            op.add_column(
                "pm_job_cards",
                sa.Column(
                    "work_order_id",
                    sa.Uuid(),
                    sa.ForeignKey("maintenance_work_orders.id"),
                    nullable=True,
                ),
            )
        pm_indexes = {index["name"] for index in inspector.get_indexes("pm_job_cards")}
        if "ix_pm_job_cards_work_order_id" not in pm_indexes:
            op.create_index("ix_pm_job_cards_work_order_id", "pm_job_cards", ["work_order_id"])
    if sa.inspect(bind).has_table("breakdown_job_cards"):
        return

    op.create_table(
        "breakdown_job_cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("job_card_number", sa.String(50), nullable=False, unique=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id")),
        sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id")),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("maintenance_work_orders.id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("job_control", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reported_failure", sa.Text()),
        sa.Column("corrective_action", sa.Text()),
        sa.Column("parts_materials", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("labour_downtime", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("test_release", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("signatures", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_breakdown_job_cards_organization_id",
        "breakdown_job_cards",
        ["organization_id"],
    )
    op.create_index(
        "ix_breakdown_job_cards_work_order_id",
        "breakdown_job_cards",
        ["work_order_id"],
    )


def downgrade() -> None:
    # Keep operational job cards intact; this revision only repairs missing schema.
    pass

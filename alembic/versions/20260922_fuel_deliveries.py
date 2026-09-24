"""Add site-level fuel delivery receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_fuel_deliveries"
down_revision = "20260921_sites_work_details"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "fuel_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fuel_type", sa.String(30), nullable=False),
        sa.Column("quantity_litres", sa.Numeric(18, 3), nullable=False),
        sa.Column("supplier", sa.String(200)),
        sa.Column("reference_number", sa.String(100)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("quantity_litres > 0", name="fuel_delivery_positive"),
    )
    op.create_table(
        "fuel_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False), sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False), sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("fuel_deliveries.id")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False), sa.Column("quantity_litres", sa.Numeric(18, 3), nullable=False), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("archived_at", sa.DateTime(timezone=True)), sa.CheckConstraint("quantity_litres > 0", name="fuel_allocation_positive"),
    )

def downgrade():
    op.drop_table("fuel_allocations")
    op.drop_table("fuel_deliveries")

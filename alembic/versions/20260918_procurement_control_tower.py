"""Add procurement (purchase orders) and control tower (scorecards, opportunities, client portal) tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_procurement_control"
down_revision = "20260918_maintenance_hse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. purchase_orders
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("po_number", sa.String(50), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("fuel_suppliers.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("inventory_requests.id"), nullable=True),
        sa.Column("status", sa.String(30), server_default="DRAFT", nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), server_default="0.0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_orders_org_supplier", "purchase_orders", ["organization_id", "supplier_id"])
    op.create_index("ix_purchase_orders_org_status", "purchase_orders", ["organization_id", "status"])
    op.create_index("ix_purchase_orders_number", "purchase_orders", ["organization_id", "po_number"], unique=True)

    # 2. purchase_order_items
    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), sa.ForeignKey("inventory_items.id"), nullable=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity_ordered", sa.Numeric(14, 2), nullable=False),
        sa.Column("quantity_received", sa.Numeric(14, 2), server_default="0.0", nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_po_items_org_po", "purchase_order_items", ["organization_id", "purchase_order_id"])

    # 3. supervisor_scorecards
    op.create_table(
        "supervisor_scorecards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("scorecard_number", sa.String(50), nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("production_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("rig_condition_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("downtime_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("hse_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("consumables_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("crew_management_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("reporting_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("stewardship_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("overall_weighted_score", sa.Numeric(5, 2), server_default="0.0", nullable=False),
        sa.Column("grade", sa.String(10), server_default="C", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_supervisor_scorecards_org_sup", "supervisor_scorecards", ["organization_id", "supervisor_id"])
    op.create_index("ix_supervisor_scorecards_org_period", "supervisor_scorecards", ["organization_id", "period_start", "period_end"])

    # 4. commercial_opportunities
    op.create_table(
        "commercial_opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("opportunity_number", sa.String(50), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("tender_stage", sa.String(50), server_default="PROSPECT", nullable=False),
        sa.Column("win_probability_pct", sa.Numeric(5, 2), server_default="50.0", nullable=False),
        sa.Column("estimated_value", sa.Numeric(14, 2), server_default="0.0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_commercial_opps_org_client", "commercial_opportunities", ["organization_id", "client_id"])
    op.create_index("ix_commercial_opps_org_stage", "commercial_opportunities", ["organization_id", "tender_stage"])

    # 5. client_project_grants
    op.create_table(
        "client_project_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("granted_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_client_grants_client_proj", "client_project_grants", ["organization_id", "client_id", "project_id"], unique=True)

    # 6. client_published_artifacts
    op.create_table(
        "client_published_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_client_published_proj", "client_published_artifacts", ["organization_id", "client_id", "project_id"])


def downgrade() -> None:
    op.drop_table("client_published_artifacts")
    op.drop_table("client_project_grants")
    op.drop_table("commercial_opportunities")
    op.drop_table("supervisor_scorecards")
    op.drop_table("purchase_order_items")
    op.drop_table("purchase_orders")

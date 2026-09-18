"""Add commercial contracts, rate cards, cost subledger, and revenue subledger tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_commercial_costing"
down_revision = "20260918_drilling_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. project_contracts
    op.create_table(
        "project_contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("contract_number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), server_default="ACTIVE", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_contracts_org_proj", "project_contracts", ["organization_id", "project_id"])
    op.create_index("ix_project_contracts_org_status", "project_contracts", ["organization_id", "status"])

    # 2. contract_rate_cards
    op.create_table(
        "contract_rate_cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("project_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rate_type", sa.String(50), nullable=False),
        sa.Column("drilling_method", sa.String(100), nullable=True),
        sa.Column("depth_from_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("depth_to_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_rate", sa.Numeric(14, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_contract_rate_cards_org_contract", "contract_rate_cards", ["organization_id", "contract_id"])

    # 3. cost_subledger_entries
    op.create_table(
        "cost_subledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("rig_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("shift_report_id", sa.Uuid(), sa.ForeignKey("drilling_shift_reports.id"), nullable=True),
        sa.Column("cost_category", sa.String(50), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit_of_measure", sa.String(30), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("exchange_rate_to_base", sa.Numeric(12, 6), server_default="1.000000", nullable=False),
        sa.Column("total_cost_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_entity_type", sa.String(50), nullable=True),
        sa.Column("source_entity_id", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_subledger_org_project", "cost_subledger_entries", ["organization_id", "project_id"])
    op.create_index("ix_cost_subledger_org_rig", "cost_subledger_entries", ["organization_id", "rig_id"])
    op.create_index("ix_cost_subledger_org_category", "cost_subledger_entries", ["organization_id", "cost_category"])
    op.create_index("ix_cost_subledger_posted", "cost_subledger_entries", ["organization_id", "posted_at"])

    # 4. revenue_subledger_entries
    op.create_table(
        "revenue_subledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("rig_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("shift_report_id", sa.Uuid(), sa.ForeignKey("drilling_shift_reports.id"), nullable=True),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("project_contracts.id"), nullable=True),
        sa.Column("rate_card_id", sa.Uuid(), sa.ForeignKey("contract_rate_cards.id"), nullable=True),
        sa.Column("revenue_category", sa.String(50), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit_rate", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_revenue", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("exchange_rate_to_base", sa.Numeric(12, 6), server_default="1.000000", nullable=False),
        sa.Column("total_revenue_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_revenue_subledger_org_project", "revenue_subledger_entries", ["organization_id", "project_id"])
    op.create_index("ix_revenue_subledger_org_rig", "revenue_subledger_entries", ["organization_id", "rig_id"])
    op.create_index("ix_revenue_subledger_org_shift", "revenue_subledger_entries", ["organization_id", "shift_report_id"])
    op.create_index("ix_revenue_subledger_posted", "revenue_subledger_entries", ["organization_id", "posted_at"])


def downgrade() -> None:
    op.drop_table("revenue_subledger_entries")
    op.drop_table("cost_subledger_entries")
    op.drop_table("contract_rate_cards")
    op.drop_table("project_contracts")

"""Add maintenance work orders, work order cost lines, HSE incidents, and HSE corrective actions tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_maintenance_hse"
down_revision = "20260918_commercial_costing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. maintenance_work_orders
    op.create_table(
        "maintenance_work_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("wo_number", sa.String(50), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("defect_id", sa.Uuid(), sa.ForeignKey("asset_defects.id"), nullable=True),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("asset_inspections.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("work_type", sa.String(30), server_default="CORRECTIVE", nullable=False),
        sa.Column("priority", sa.String(20), server_default="MEDIUM", nullable=False),
        sa.Column("status", sa.String(30), server_default="OPEN", nullable=False),
        sa.Column("failure_taxonomy", sa.String(50), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("remedy", sa.Text(), nullable=True),
        sa.Column("downtime_hours", sa.Numeric(10, 2), server_default="0.0", nullable=False),
        sa.Column("estimated_lost_contribution", sa.Numeric(14, 2), server_default="0.0", nullable=False),
        sa.Column("assigned_technician_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("meter_reading", sa.Numeric(14, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_maintenance_wo_org_asset", "maintenance_work_orders", ["organization_id", "asset_id"])
    op.create_index("ix_maintenance_wo_org_status", "maintenance_work_orders", ["organization_id", "status"])
    op.create_index("ix_maintenance_wo_number", "maintenance_work_orders", ["organization_id", "wo_number"], unique=True)

    # 2. work_order_cost_lines
    op.create_table(
        "work_order_cost_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("maintenance_work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cost_type", sa.String(30), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("posted_to_subledger", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_wo_cost_lines_org_wo", "work_order_cost_lines", ["organization_id", "work_order_id"])

    # 3. hse_incidents
    op.create_table(
        "hse_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("incident_number", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("incident_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), server_default="MEDIUM", nullable=False),
        sa.Column("status", sa.String(30), server_default="REPORTED", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("reported_by_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("immediate_actions_taken", sa.Text(), nullable=True),
        sa.Column("root_cause_analysis", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hse_incidents_org_project", "hse_incidents", ["organization_id", "project_id"])
    op.create_index("ix_hse_incidents_org_status", "hse_incidents", ["organization_id", "status"])
    op.create_index("ix_hse_incidents_number", "hse_incidents", ["organization_id", "incident_number"], unique=True)

    # 4. hse_corrective_actions
    op.create_table(
        "hse_corrective_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("action_number", sa.String(50), nullable=False),
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("hse_incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("assigned_to_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), server_default="OPEN", nullable=False),
        sa.Column("closure_notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hse_actions_org_incident", "hse_corrective_actions", ["organization_id", "incident_id"])
    op.create_index("ix_hse_actions_org_assignee", "hse_corrective_actions", ["organization_id", "assigned_to_id"])
    op.create_index("ix_hse_actions_org_status", "hse_corrective_actions", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_table("hse_corrective_actions")
    op.drop_table("hse_incidents")
    op.drop_table("work_order_cost_lines")
    op.drop_table("maintenance_work_orders")

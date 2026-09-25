"""Structured equipment and maintenance assessment reports.

Revision ID: 20261007_maint_assess
Revises: 20261006_notif_action_urls
"""

from alembic import op
import sqlalchemy as sa


revision = "20261007_maint_assess"
down_revision = "20261006_notif_action_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_assessment_reports",
        sa.Column("report_number", sa.String(50), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("site_location_id", sa.Uuid(), nullable=True),
        sa.Column("reporting_period_start", sa.Date(), nullable=False),
        sa.Column("reporting_period_end", sa.Date(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("prepared_by_employee_id", sa.Uuid(), nullable=True),
        sa.Column("prepared_by_name", sa.String(200), nullable=False),
        sa.Column("prepared_by_position", sa.String(150), nullable=True),
        sa.Column("submitted_to", sa.String(200), nullable=True),
        sa.Column("status", sa.String(30), server_default="DRAFT", nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("equipment_asset_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("equipment_fleet", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("maintenance_assessment", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("preventive_improvements", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("spare_parts_actions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("manpower_requirements", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("control_documents", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("action_plan", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("maintenance_kpis", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["site_location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["prepared_by_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "report_number", name="uq_maintenance_assessment_report_number"),
    )
    op.create_index(
        "ix_maintenance_assessment_reports_project_id",
        "maintenance_assessment_reports", ["project_id"], unique=False,
    )
    op.create_index(
        "ix_maintenance_assessment_reports_organization_id",
        "maintenance_assessment_reports", ["organization_id"], unique=False,
    )
    op.create_index(
        "ix_maintenance_assessment_reports_org_period",
        "maintenance_assessment_reports", ["organization_id", "reporting_period_start", "reporting_period_end"], unique=False,
    )
    op.create_index(
        "ix_maintenance_assessment_reports_archived_at",
        "maintenance_assessment_reports", ["archived_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_maintenance_assessment_reports_archived_at", table_name="maintenance_assessment_reports")
    op.drop_index("ix_maintenance_assessment_reports_org_period", table_name="maintenance_assessment_reports")
    op.drop_index("ix_maintenance_assessment_reports_project_id", table_name="maintenance_assessment_reports")
    op.drop_index("ix_maintenance_assessment_reports_organization_id", table_name="maintenance_assessment_reports")
    op.drop_table("maintenance_assessment_reports")

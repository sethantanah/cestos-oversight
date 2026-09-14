"""Project field reports and drilling KPIs."""

import sqlalchemy as sa

from alembic import op

revision = "20260912_project_reports"
down_revision = "20260910_op_enhancements"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("site_name", sa.String(200), nullable=False),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("metres", sa.Numeric(18, 2)),
        sa.Column("drill_holes", sa.Integer()),
        sa.Column("average_depth", sa.Numeric(18, 2)),
        sa.Column("author_name", sa.String(300), nullable=False),
        sa.Column("storage_path", sa.Text()),
        sa.Column("file_name", sa.String(255)),
        sa.Column("mime_type", sa.String(150)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "report_type IN ('DRILLING_UPDATE','PROGRESS_UPDATE','SAFETY_REPORT','SITE_ISSUE')",
            name="project_report_type",
        ),
        sa.CheckConstraint(
            "metres >= 0 AND drill_holes >= 0 AND average_depth >= 0",
            name="project_report_positive",
        ),
    )
    op.create_index("ix_project_reports_organization_id", "project_reports", ["organization_id"])
    op.create_index(
        "ix_project_reports_date",
        "project_reports",
        ["organization_id", "project_id", "report_date"],
    )


def downgrade():
    op.drop_table("project_reports")

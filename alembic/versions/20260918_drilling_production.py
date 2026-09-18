"""Add drilling production tables: drilling_programs, drill_holes, drilling_shift_reports, drilling_shift_intervals, drilling_shift_time_segments, drilling_shift_crews."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_drilling_production"
down_revision = "17f0842562e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. drilling_programs
    op.create_table(
        "drilling_programs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("target_metres", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(30), server_default="PLANNING", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_drilling_programs_org_project", "drilling_programs", ["organization_id", "project_id"])
    op.create_index("ix_drilling_programs_org_status", "drilling_programs", ["organization_id", "status"])

    # 2. drill_holes
    op.create_table(
        "drill_holes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("program_id", sa.Uuid(), sa.ForeignKey("drilling_programs.id"), nullable=True),
        sa.Column("hole_number", sa.String(100), nullable=False),
        sa.Column("drilling_method", sa.String(100), nullable=True),
        sa.Column("target_depth_m", sa.Numeric(18, 2), nullable=True),
        sa.Column("final_depth_m", sa.Numeric(18, 2), nullable=True),
        sa.Column("azimuth_deg", sa.Numeric(6, 2), nullable=True),
        sa.Column("dip_deg", sa.Numeric(6, 2), nullable=True),
        sa.Column("status", sa.String(30), server_default="PLANNED", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_drill_holes_org_project", "drill_holes", ["organization_id", "project_id"])
    op.create_index("ix_drill_holes_org_program", "drill_holes", ["organization_id", "program_id"])
    op.create_index("ix_drill_holes_number", "drill_holes", ["organization_id", "project_id", "hole_number"], unique=True)

    # 3. drilling_shift_reports
    op.create_table(
        "drilling_shift_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("report_number", sa.String(30), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("rig_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("program_id", sa.Uuid(), sa.ForeignKey("drilling_programs.id"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shift_type", sa.String(20), server_default="DAY", nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("status", sa.String(30), server_default="DRAFT", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("return_reason", sa.Text(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("total_metres", sa.Numeric(18, 2), server_default="0.0", nullable=False),
        sa.Column("total_productive_hours", sa.Numeric(18, 2), server_default="0.0", nullable=False),
        sa.Column("total_nonproductive_hours", sa.Numeric(18, 2), server_default="0.0", nullable=False),
        sa.Column("avg_core_recovery_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_drilling_shifts_org_project", "drilling_shift_reports", ["organization_id", "project_id"])
    op.create_index("ix_drilling_shifts_org_rig", "drilling_shift_reports", ["organization_id", "rig_id"])
    op.create_index("ix_drilling_shifts_org_date", "drilling_shift_reports", ["organization_id", "date"])
    op.create_index("ix_drilling_shifts_org_status", "drilling_shift_reports", ["organization_id", "status"])
    op.create_index("uq_drilling_shifts_rig_date_shift", "drilling_shift_reports", ["organization_id", "rig_id", "date", "shift_type"], unique=True)

    # 4. drilling_shift_intervals
    op.create_table(
        "drilling_shift_intervals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("shift_report_id", sa.Uuid(), sa.ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drill_hole_id", sa.Uuid(), sa.ForeignKey("drill_holes.id"), nullable=False),
        sa.Column("from_depth_m", sa.Numeric(18, 2), nullable=False),
        sa.Column("to_depth_m", sa.Numeric(18, 2), nullable=False),
        sa.Column("drilled_metres", sa.Numeric(18, 2), nullable=False),
        sa.Column("core_recovered_m", sa.Numeric(18, 2), nullable=True),
        sa.Column("core_recovery_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("drilling_method", sa.String(50), nullable=True),
        sa.Column("ground_conditions", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_shift_intervals_report", "drilling_shift_intervals", ["organization_id", "shift_report_id"])
    op.create_index("ix_shift_intervals_hole", "drilling_shift_intervals", ["organization_id", "drill_hole_id"])

    # 5. drilling_shift_time_segments
    op.create_table(
        "drilling_shift_time_segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("shift_report_id", sa.Uuid(), sa.ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("hours", sa.Numeric(18, 2), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_shift_time_segments_report", "drilling_shift_time_segments", ["organization_id", "shift_report_id"])

    # 6. drilling_shift_crews
    op.create_table(
        "drilling_shift_crews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("shift_report_id", sa.Uuid(), sa.ForeignKey("drilling_shift_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("role_on_shift", sa.String(100), nullable=False),
        sa.Column("hours_worked", sa.Numeric(18, 2), server_default="12.0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_shift_crews_report", "drilling_shift_crews", ["organization_id", "shift_report_id"])
    op.create_index("ix_shift_crews_employee", "drilling_shift_crews", ["organization_id", "employee_id"])


def downgrade() -> None:
    op.drop_index("ix_shift_crews_employee", table_name="drilling_shift_crews")
    op.drop_index("ix_shift_crews_report", table_name="drilling_shift_crews")
    op.drop_table("drilling_shift_crews")

    op.drop_index("ix_shift_time_segments_report", table_name="drilling_shift_time_segments")
    op.drop_table("drilling_shift_time_segments")

    op.drop_index("ix_shift_intervals_hole", table_name="drilling_shift_intervals")
    op.drop_index("ix_shift_intervals_report", table_name="drilling_shift_intervals")
    op.drop_table("drilling_shift_intervals")

    op.drop_index("uq_drilling_shifts_rig_date_shift", table_name="drilling_shift_reports")
    op.drop_index("ix_drilling_shifts_org_status", table_name="drilling_shift_reports")
    op.drop_index("ix_drilling_shifts_org_date", table_name="drilling_shift_reports")
    op.drop_index("ix_drilling_shifts_org_rig", table_name="drilling_shift_reports")
    op.drop_index("ix_drilling_shifts_org_project", table_name="drilling_shift_reports")
    op.drop_table("drilling_shift_reports")

    op.drop_index("ix_drill_holes_number", table_name="drill_holes")
    op.drop_index("ix_drill_holes_org_program", table_name="drill_holes")
    op.drop_index("ix_drill_holes_org_project", table_name="drill_holes")
    op.drop_table("drill_holes")

    op.drop_index("ix_drilling_programs_org_status", table_name="drilling_programs")
    op.drop_index("ix_drilling_programs_org_project", table_name="drilling_programs")
    op.drop_table("drilling_programs")

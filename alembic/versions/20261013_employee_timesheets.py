"""Add monthly employee timesheets with daily hour entries."""

from alembic import op
import sqlalchemy as sa


revision = "20261013_employee_timesheets"
down_revision = "20261012_equipment_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_timesheets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("site_name", sa.String(length=200), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "employee_id", "period_start", name="uq_employee_timesheet_period"),
    )
    op.create_index("ix_employee_timesheets_organization_id", "employee_timesheets", ["organization_id"])
    op.create_index("ix_employee_timesheets_employee_id", "employee_timesheets", ["employee_id"])
    op.create_index("ix_employee_timesheets_org_period", "employee_timesheets", ["organization_id", "period_start"])

    op.create_table(
        "employee_timesheet_days",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timesheet_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Numeric(6, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["timesheet_id"], ["employee_timesheets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("timesheet_id", "work_date", name="uq_employee_timesheet_day"),
        sa.CheckConstraint("hours >= 0 AND hours <= 24", name="ck_employee_timesheet_hours_range"),
    )
    op.create_index("ix_employee_timesheet_days_timesheet_id", "employee_timesheet_days", ["timesheet_id"])
    op.create_index("ix_employee_timesheet_days_organization_id", "employee_timesheet_days", ["organization_id"])
    op.create_index("ix_employee_timesheet_days_date", "employee_timesheet_days", ["work_date"])


def downgrade() -> None:
    op.drop_table("employee_timesheet_days")
    op.drop_table("employee_timesheets")

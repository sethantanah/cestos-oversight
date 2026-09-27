"""Retain unmatched employee and project names on imported timesheets."""

from alembic import op
import sqlalchemy as sa


revision = "20261015_timesheet_source_names"
down_revision = "20261014_emp_status_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("employee_timesheets", "employee_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_constraint("uq_employee_timesheet_period", "employee_timesheets", type_="unique")
    op.add_column("employee_timesheets", sa.Column("employee_name", sa.String(length=200), nullable=True))
    op.add_column("employee_timesheets", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("employee_timesheets", sa.Column("project_name", sa.String(length=200), nullable=True))
    op.add_column("employee_timesheets", sa.Column("scope_project_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_employee_timesheets_project_id_projects", "employee_timesheets", "projects", ["project_id"], ["id"])
    op.create_foreign_key("fk_employee_timesheets_scope_project_id_projects", "employee_timesheets", "projects", ["scope_project_id"], ["id"])
    op.create_index("ix_employee_timesheets_project_id", "employee_timesheets", ["project_id"])
    op.create_index("ix_employee_timesheets_scope_project_id", "employee_timesheets", ["scope_project_id"])
    op.create_index("ix_employee_timesheets_org_employee_period", "employee_timesheets", ["organization_id", "employee_id", "period_start"])
    op.create_index("uq_employee_timesheet_employee_period", "employee_timesheets", ["organization_id", "employee_id", "period_start"], unique=True, postgresql_where=sa.text("employee_id IS NOT NULL"))
    op.create_index("uq_employee_timesheet_custom_name_period", "employee_timesheets", ["organization_id", sa.text("lower(employee_name)"), "period_start"], unique=True, postgresql_where=sa.text("employee_id IS NULL AND employee_name IS NOT NULL"))
    op.execute("""
        UPDATE employee_timesheets AS timesheet
        SET employee_name = concat_ws(' ', employee.first_name, employee.middle_name, employee.last_name)
        FROM employees AS employee
        WHERE timesheet.employee_id = employee.id AND timesheet.employee_name IS NULL
    """)


def downgrade() -> None:
    op.drop_index("uq_employee_timesheet_custom_name_period", table_name="employee_timesheets")
    op.drop_index("uq_employee_timesheet_employee_period", table_name="employee_timesheets")
    op.drop_index("ix_employee_timesheets_org_employee_period", table_name="employee_timesheets")
    op.drop_index("ix_employee_timesheets_scope_project_id", table_name="employee_timesheets")
    op.drop_index("ix_employee_timesheets_project_id", table_name="employee_timesheets")
    op.drop_constraint("fk_employee_timesheets_scope_project_id_projects", "employee_timesheets", type_="foreignkey")
    op.drop_constraint("fk_employee_timesheets_project_id_projects", "employee_timesheets", type_="foreignkey")
    op.drop_column("employee_timesheets", "scope_project_id")
    op.drop_column("employee_timesheets", "project_name")
    op.drop_column("employee_timesheets", "project_id")
    op.drop_column("employee_timesheets", "employee_name")
    op.create_unique_constraint("uq_employee_timesheet_period", "employee_timesheets", ["organization_id", "employee_id", "period_start"])
    op.alter_column("employee_timesheets", "employee_id", existing_type=sa.Uuid(), nullable=False)

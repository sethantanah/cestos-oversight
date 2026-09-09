"""Employee activity time logs and leave requests."""
import sqlalchemy as sa
from alembic import op

revision = "0006_time_leave"
down_revision = "19b94659bc6a"
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
    ]


def upgrade():
    op.create_table("time_logs", *common_columns(),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("check_in", sa.DateTime(timezone=True)),
        sa.Column("check_out", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Enum("PENDING", "COMPLETED", "CANCELLED", name="time_log_status"), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("logged_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
    )
    op.create_table("leave_requests", *common_columns(),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.Enum("PENDING", "APPROVED", "REJECTED", name="leave_request_status"), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("attachment_url", sa.String(1024)),
        sa.Column("notes", sa.Text()),
    )
    for table in ("time_logs", "leave_requests"):
        for column in ("organization_id", "employee_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_timelogs_employee", "time_logs", ["organization_id", "employee_id"])
    op.create_index("ix_timelogs_date", "time_logs", ["organization_id", "date"])
    op.create_index("ix_leaves_employee", "leave_requests", ["organization_id", "employee_id"])
    op.create_index("ix_leaves_status", "leave_requests", ["organization_id", "status"])


def downgrade():
    op.drop_table("leave_requests")
    op.drop_table("time_logs")
    sa.Enum(name="leave_request_status").drop(op.get_bind())
    sa.Enum(name="time_log_status").drop(op.get_bind())

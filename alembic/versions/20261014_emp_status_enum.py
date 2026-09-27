"""Add OUT_OF_CONTRACT to the employment status enum."""

from alembic import op


revision = "20261014_emp_status_enum"
down_revision = "7a0ebcb0e5cf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE employment_status ADD VALUE IF NOT EXISTS 'OUT_OF_CONTRACT'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed once rows may use them.
    pass

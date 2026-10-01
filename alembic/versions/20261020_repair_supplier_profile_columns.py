"""Ensure shared supplier profile columns exist on older databases.

Revision ID: 20261020_supplier_profile
Revises: 20261019_vendor_master
"""

from alembic import op


revision = "20261020_supplier_profile"
down_revision = "20261019_vendor_master"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These fields predate the Finance vendor master, but some deployed databases
    # recorded the earlier revision without applying its schema changes.
    op.execute("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS address TEXT")
    op.execute(
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS country VARCHAR(100)"
    )


def downgrade() -> None:
    # Keep profile data intact; this migration repairs potentially drifted schemas.
    pass

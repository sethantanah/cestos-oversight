"""Add is_supervisory_role column to positions table."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_position_supervisory"
down_revision = "20260912_client_profile_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("is_supervisory_role", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("positions", "is_supervisory_role")

"""Add is_field_portal_only column to users table."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_user_field_portal"
down_revision = "20260919_project_contract_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("users")]
    if "is_field_portal_only" not in cols:
        op.add_column(
            "users",
            sa.Column("is_field_portal_only", sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("users")]
    if "is_field_portal_only" in cols:
        op.drop_column("users", "is_field_portal_only")

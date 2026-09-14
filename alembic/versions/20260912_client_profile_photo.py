"""Add client logo storage URL expected by the client model."""

import sqlalchemy as sa

from alembic import op

revision = "20260912_client_profile_photo"
down_revision = "20260912_project_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("profile_photo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "profile_photo_url")

"""Remove the assessment-only custom site label.

Revision ID: 20261009_drop_assess_site
Revises: 20261008_maint_custom_labels
"""

from alembic import op
import sqlalchemy as sa


revision = "20261009_drop_assess_site"
down_revision = "20261008_maint_custom_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("maintenance_assessment_reports", "site_name_custom")


def downgrade() -> None:
    op.add_column("maintenance_assessment_reports", sa.Column("site_name_custom", sa.String(200), nullable=True))

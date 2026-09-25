"""Allow custom project and site labels on maintenance assessments.

Revision ID: 20261008_maint_custom_labels
Revises: 20261007_maint_assess
"""

from alembic import op
import sqlalchemy as sa


revision = "20261008_maint_custom_labels"
down_revision = "20261007_maint_assess"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("maintenance_assessment_reports", sa.Column("project_name_custom", sa.String(200), nullable=True))
    op.add_column("maintenance_assessment_reports", sa.Column("site_name_custom", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("maintenance_assessment_reports", "site_name_custom")
    op.drop_column("maintenance_assessment_reports", "project_name_custom")

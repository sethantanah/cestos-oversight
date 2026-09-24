"""add_portal_type_to_users

Revision ID: dfbccb0259eb
Revises: 20260922_pm_job_cards
"""
from alembic import op
import sqlalchemy as sa

revision = 'dfbccb0259eb'
down_revision = '20260922_pm_job_cards'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add portal_type column to users table.
    # Valid values: FULL | FIELD | HR | FINANCE | FIELD_ADMIN
    # Backfill existing field-portal-only users to FIELD.
    op.add_column(
        'users',
        sa.Column('portal_type', sa.String(length=20), server_default='FULL', nullable=False),
    )
    op.execute(
        "UPDATE users SET portal_type = 'FIELD' WHERE is_field_portal_only = TRUE"
    )


def downgrade() -> None:
    op.drop_column('users', 'portal_type')

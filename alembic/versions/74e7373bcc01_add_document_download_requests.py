"""add_document_download_requests

Revision ID: 74e7373bcc01
Revises: 20260923_merge_expenses_portal
"""
from alembic import op
import sqlalchemy as sa

revision = '74e7373bcc01'
down_revision = '20260923_merge_expenses_portal'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_download_requests',
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('reviewed_by_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_notes', sa.String(length=500), nullable=True),
        sa.Column('download_token', sa.String(length=64), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['employee_documents.id'], name=op.f('fk_document_download_requests_document_id_employee_documents')),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_document_download_requests_employee_id_employees')),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_document_download_requests_organization_id_organizations')),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id'], name=op.f('fk_document_download_requests_requested_by_id_users')),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], name=op.f('fk_document_download_requests_reviewed_by_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_document_download_requests'))
    )
    op.create_index(op.f('ix_document_download_requests_document_id'), 'document_download_requests', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_download_requests_employee_id'), 'document_download_requests', ['employee_id'], unique=False)
    op.create_index(op.f('ix_document_download_requests_organization_id'), 'document_download_requests', ['organization_id'], unique=False)
    op.create_index(op.f('ix_document_download_requests_requested_by_id'), 'document_download_requests', ['requested_by_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_download_requests_requested_by_id'), table_name='document_download_requests')
    op.drop_index(op.f('ix_document_download_requests_organization_id'), table_name='document_download_requests')
    op.drop_index(op.f('ix_document_download_requests_employee_id'), table_name='document_download_requests')
    op.drop_index(op.f('ix_document_download_requests_document_id'), table_name='document_download_requests')
    op.drop_table('document_download_requests')

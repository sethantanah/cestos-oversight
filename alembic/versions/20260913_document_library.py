"""Private document catalog, full-text index and document administration grants."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260913_document_library"
down_revision = "20260913_maint_recurring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id")),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("private_to_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("index_status", sa.String(30), nullable=False),
        sa.Column("index_message", sa.String(500)),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("chunks", postgresql.JSONB(), nullable=False),
        sa.Column("vector_path", sa.Text()),
        sa.UniqueConstraint(
            "organization_id", "source_type", "source_id", name="uq_library_source"
        ),
        sa.CheckConstraint(
            "visibility IN ('PRIVATE','PUBLIC','SUPER_PRIVATE')", name="library_visibility"
        ),
        sa.CheckConstraint(
            "visibility != 'SUPER_PRIVATE' OR private_to_id IS NOT NULL",
            name="library_private_holder",
        ),
    )
    for name, columns in [
        ("ix_library_category", ["organization_id", "category"]),
        ("ix_library_owner", ["organization_id", "owner_id"]),
        ("ix_library_pending", ["index_status"]),
        ("ix_library_documents_organization_id", ["organization_id"]),
    ]:
        op.create_index(name, "library_documents", columns)
    op.create_index("ix_library_tags", "library_documents", ["tags"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_library_text ON library_documents "
        "USING gin (to_tsvector('simple', extracted_text))"
    )
    op.execute(
        "INSERT INTO permissions (id, code, description) VALUES "
        "(gen_random_uuid(), 'documents.admin', "
        "'Manage document privacy including Super Private files'), "
        "(gen_random_uuid(), 'documents.read_all', 'Read ordinary private organization documents') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade():
    op.drop_table("library_documents")

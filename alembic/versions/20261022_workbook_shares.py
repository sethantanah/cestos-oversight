"""Revocable workbook sharing with revision checks."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "20261022_workbook_shares"
down_revision = "20261021_opex_category"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("workbook_shares",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("organization_id",sa.Uuid(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("owner_id",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("workbook_id",sa.String(100),nullable=False),
        sa.Column("token_hash",sa.String(64),nullable=False,unique=True),
        sa.Column("workbook",postgresql.JSONB(),nullable=False),
        sa.Column("editor_ids",postgresql.JSONB(),nullable=False),
        sa.Column("revision",sa.Integer(),nullable=False),
        sa.Column("history",postgresql.JSONB(),nullable=False),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("revoked",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    for field in ["organization_id","owner_id","workbook_id"]:op.create_index("ix_workbook_shares_"+field,"workbook_shares",[field])

def downgrade():
    op.drop_table("workbook_shares")

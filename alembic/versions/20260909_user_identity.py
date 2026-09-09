"""Align the optional external identity field with the current user model."""
from alembic import op
import sqlalchemy as sa
revision='20260909_user_identity'
down_revision='20260909_inventory_import'
branch_labels=None
depends_on=None

def upgrade() -> None:
    if 'supabase_user_id' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}:
        op.add_column('users',sa.Column('supabase_user_id',sa.String(128),nullable=True))

def downgrade() -> None:
    # Retain linked identity values during an inventory rollback.
    pass

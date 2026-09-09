"""Inventory import previews and additional structural checks."""
from alembic import op
import sqlalchemy as sa
revision='20260909_inventory_import'
down_revision='20260909_inventory'
branch_labels=None
depends_on=None

def upgrade() -> None:
    op.create_table('inventory_imports',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('created_by_id',sa.Uuid(),sa.ForeignKey('users.id')),
        sa.Column('updated_by_id',sa.Uuid(),sa.ForeignKey('users.id')),
        sa.Column('kind',sa.String(30),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('filename',sa.String(255),nullable=False),sa.Column('rows',sa.JSON(),nullable=False),sa.Column('errors',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('completed_at',sa.DateTime(timezone=True)))
    op.create_index('ix_inventory_imports_organization_id','inventory_imports',['organization_id'])
    op.create_check_constraint('item_tracking_method','inventory_items',"tracking_method IN ('QUANTITY','BATCH','SERIALIZED')")
    op.create_check_constraint('item_criticality','inventory_items',"criticality IN ('LOW','MEDIUM','HIGH','CRITICAL')")
    op.create_check_constraint('transaction_posted','inventory_transactions',"status = 'POSTED'")

def downgrade() -> None:
    op.drop_constraint(op.f('ck_inventory_transactions_transaction_posted'),'inventory_transactions',type_='check')
    op.drop_constraint(op.f('ck_inventory_items_item_criticality'),'inventory_items',type_='check')
    op.drop_constraint(op.f('ck_inventory_items_item_tracking_method'),'inventory_items',type_='check')
    op.drop_table('inventory_imports')

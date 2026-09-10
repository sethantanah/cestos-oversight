"""Fuel suppliers, fuel reductions, and log attachments."""

from alembic import op

revision = "20260910_op_enhancements"
down_revision = "20260910_operational_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
CREATE TABLE IF NOT EXISTS fuel_suppliers (
    id UUID NOT NULL,
    organization_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    created_by_id UUID,
    updated_by_id UUID,
    CONSTRAINT pk_fuel_suppliers PRIMARY KEY (id),
    CONSTRAINT fk_fuel_suppliers_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id),
    CONSTRAINT fk_fuel_suppliers_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id),
    CONSTRAINT fk_fuel_suppliers_updated_by_id_users FOREIGN KEY(updated_by_id) REFERENCES users (id)
)
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_fuel_supplier_name ON fuel_suppliers (organization_id, name)")

    op.execute(
        """
CREATE TABLE IF NOT EXISTS asset_fuel_reductions (
    id UUID NOT NULL,
    organization_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    fuel_log_id UUID,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    litres_reduced NUMERIC(18, 3) NOT NULL,
    remaining_litres NUMERIC(18, 3),
    reduction_reason VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    created_by_id UUID,
    updated_by_id UUID,
    CONSTRAINT pk_asset_fuel_reductions PRIMARY KEY (id),
    CONSTRAINT ck_asset_fuel_reductions_positive CHECK (litres_reduced > 0),
    CONSTRAINT fk_asset_fuel_reductions_asset_id_assets FOREIGN KEY(asset_id) REFERENCES assets (id),
    CONSTRAINT fk_asset_fuel_reductions_fuel_log_id FOREIGN KEY(fuel_log_id) REFERENCES asset_fuel_logs (id) ON DELETE SET NULL,
    CONSTRAINT fk_asset_fuel_reductions_organization_id FOREIGN KEY(organization_id) REFERENCES organizations (id),
    CONSTRAINT fk_asset_fuel_reductions_created_by_id FOREIGN KEY(created_by_id) REFERENCES users (id),
    CONSTRAINT fk_asset_fuel_reductions_updated_by_id FOREIGN KEY(updated_by_id) REFERENCES users (id)
)
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_fuel_reduction_time ON asset_fuel_reductions (organization_id, asset_id, recorded_at)"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS asset_log_files (
    id UUID NOT NULL,
    organization_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    log_type VARCHAR(30) NOT NULL,
    log_id UUID NOT NULL,
    title VARCHAR(200) NOT NULL,
    storage_path TEXT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(150),
    size_bytes INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    created_by_id UUID,
    updated_by_id UUID,
    CONSTRAINT pk_asset_log_files PRIMARY KEY (id),
    CONSTRAINT fk_asset_log_files_asset_id_assets FOREIGN KEY(asset_id) REFERENCES assets (id),
    CONSTRAINT fk_asset_log_files_organization_id FOREIGN KEY(organization_id) REFERENCES organizations (id),
    CONSTRAINT fk_asset_log_files_created_by_id FOREIGN KEY(created_by_id) REFERENCES users (id),
    CONSTRAINT fk_asset_log_files_updated_by_id FOREIGN KEY(updated_by_id) REFERENCES users (id)
)
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_log_files_lookup ON asset_log_files (organization_id, asset_id, log_type, log_id)"
    )


def downgrade():
    op.drop_table("asset_log_files")
    op.drop_table("asset_fuel_reductions")
    op.drop_table("fuel_suppliers")

"""Asset fuel, maintenance and project collaboration records."""

from alembic import op

revision = "20260910_operational_logs"
down_revision = "20260909_user_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE asset_fuel_logs (\n\tasset_id UUID NOT NULL, \n\tproject_id UUID, \n\trecorded_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfuel_type VARCHAR(30) NOT NULL, \n\tquantity_litres NUMERIC(18, 3) NOT NULL, \n\tunit_cost NUMERIC(18, 4) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tmeter_reading NUMERIC(18, 2), \n\tsupplier VARCHAR(200), \n\treference_number VARCHAR(100), \n\tnotes TEXT, \n\tid UUID NOT NULL, \n\torganization_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by_id UUID, \n\tupdated_by_id UUID, \n\tCONSTRAINT pk_asset_fuel_logs PRIMARY KEY (id), \n\tCONSTRAINT ck_asset_fuel_logs_fuel_positive CHECK (quantity_litres > 0 AND unit_cost >= 0), \n\tCONSTRAINT fk_asset_fuel_logs_asset_id_assets FOREIGN KEY(asset_id) REFERENCES assets (id), \n\tCONSTRAINT fk_asset_fuel_logs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id), \n\tCONSTRAINT fk_asset_fuel_logs_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id), \n\tCONSTRAINT fk_asset_fuel_logs_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id), \n\tCONSTRAINT fk_asset_fuel_logs_updated_by_id_users FOREIGN KEY(updated_by_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_asset_fuel_logs_organization_id ON asset_fuel_logs (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_asset_fuel_time ON asset_fuel_logs (organization_id, asset_id, recorded_at)"
    )
    op.execute(
        "\nCREATE TABLE asset_maintenance_jobs (\n\tasset_id UUID NOT NULL, \n\tproject_id UUID, \n\ttitle VARCHAR(200) NOT NULL, \n\tdescription TEXT, \n\tmaintenance_type VARCHAR(30) NOT NULL, \n\tpriority VARCHAR(20) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tscheduled_date DATE, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tmeter_reading NUMERIC(18, 2), \n\tprovider VARCHAR(200), \n\tcost NUMERIC(18, 2) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tcompletion_notes TEXT, \n\tid UUID NOT NULL, \n\torganization_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by_id UUID, \n\tupdated_by_id UUID, \n\tCONSTRAINT pk_asset_maintenance_jobs PRIMARY KEY (id), \n\tCONSTRAINT ck_asset_maintenance_jobs_maintenance_cost_positive CHECK (cost >= 0), \n\tCONSTRAINT ck_asset_maintenance_jobs_maintenance_status CHECK (status IN ('OPEN','IN_PROGRESS','COMPLETED','CANCELLED')), \n\tCONSTRAINT fk_asset_maintenance_jobs_asset_id_assets FOREIGN KEY(asset_id) REFERENCES assets (id), \n\tCONSTRAINT fk_asset_maintenance_jobs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id), \n\tCONSTRAINT fk_asset_maintenance_jobs_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id), \n\tCONSTRAINT fk_asset_maintenance_jobs_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id), \n\tCONSTRAINT fk_asset_maintenance_jobs_updated_by_id_users FOREIGN KEY(updated_by_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_asset_maintenance_jobs_organization_id ON asset_maintenance_jobs (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_asset_maintenance_status ON asset_maintenance_jobs (organization_id, asset_id, status)"
    )
    op.execute(
        "\nCREATE TABLE project_records (\n\tproject_id UUID NOT NULL, \n\trecord_type VARCHAR(20) NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tdescription TEXT, \n\tstorage_path TEXT, \n\tfile_name VARCHAR(255), \n\tmime_type VARCHAR(150), \n\tsize_bytes INTEGER, \n\tid UUID NOT NULL, \n\torganization_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by_id UUID, \n\tupdated_by_id UUID, \n\tCONSTRAINT pk_project_records PRIMARY KEY (id), \n\tCONSTRAINT ck_project_records_project_record_type CHECK (record_type IN ('FILE','NOTE','COMMENT')), \n\tCONSTRAINT fk_project_records_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id), \n\tCONSTRAINT fk_project_records_organization_id_organizations FOREIGN KEY(organization_id) REFERENCES organizations (id), \n\tCONSTRAINT fk_project_records_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id), \n\tCONSTRAINT fk_project_records_updated_by_id_users FOREIGN KEY(updated_by_id) REFERENCES users (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_project_records_organization_id ON project_records (organization_id)"
    )
    op.execute(
        "CREATE INDEX ix_project_record_time ON project_records (organization_id, project_id, created_at)"
    )


def downgrade():
    op.drop_table("project_records")
    op.drop_table("asset_maintenance_jobs")
    op.drop_table("asset_fuel_logs")

"""Link drilling records to sites and repair opportunity attachment columns."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_sites_work_details"
down_revision = "20260921_notification_indexes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    additions = {
        "drill_holes": [sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=True)],
        "drilling_shift_reports": [sa.Column("site_location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=True)],
        "commercial_opportunities": [sa.Column("attachment_name", sa.String(255)), sa.Column("attachment_url", sa.Text())],
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    for table in ("drill_holes", "drilling_shift_reports"):
        op.create_index(f"ix_{table}_site_location_id", table, ["site_location_id"], if_not_exists=True)
    # Backfill only when a project has exactly one eligible site; never guess between sites.
    for table in ("drill_holes", "drilling_shift_reports"):
        op.execute(sa.text(f"""UPDATE {table} AS record SET site_location_id = site.id
            FROM locations site WHERE record.site_location_id IS NULL
            AND site.project_id = record.project_id AND site.organization_id = record.organization_id
            AND site.is_active AND site.archived_at IS NULL AND site.location_type <> 'HEAD_OFFICE'
            AND 1 = (SELECT count(*) FROM locations other WHERE other.project_id = record.project_id
                AND other.organization_id = record.organization_id AND other.is_active
                AND other.archived_at IS NULL AND other.location_type <> 'HEAD_OFFICE')"""))


def downgrade():
    for table in ("drill_holes", "drilling_shift_reports"):
        op.drop_index(f"ix_{table}_site_location_id", table_name=table)
        op.drop_column(table, "site_location_id")
    op.drop_column("commercial_opportunities", "attachment_name")
    op.drop_column("commercial_opportunities", "attachment_url")

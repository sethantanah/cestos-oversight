"""Track tenant data changes for cross-device portal refreshes.

Revision ID: 20261016_data_change_feed
Revises: 20261015_timesheet_source_names
"""

from alembic import op
import sqlalchemy as sa


revision = "20261016_data_change_feed"
down_revision = "20261015_timesheet_source_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_data_changes",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("organization_id", "table_name", name="pk_platform_data_changes"),
    )
    op.create_index(
        "ix_platform_data_changes_org_changed_at",
        "platform_data_changes",
        ["organization_id", "changed_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cestos_track_organization_data_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            old_org uuid;
            new_org uuid;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                old_org := NULLIF(to_jsonb(OLD)->>'organization_id', '')::uuid;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                new_org := NULLIF(to_jsonb(NEW)->>'organization_id', '')::uuid;
            END IF;

            IF old_org IS NOT NULL THEN
                INSERT INTO platform_data_changes (organization_id, table_name, revision, changed_at)
                VALUES (old_org, TG_TABLE_NAME, 1, clock_timestamp())
                ON CONFLICT (organization_id, table_name) DO UPDATE
                SET revision = platform_data_changes.revision + 1,
                    changed_at = clock_timestamp();
            END IF;

            IF new_org IS NOT NULL AND new_org IS DISTINCT FROM old_org THEN
                INSERT INTO platform_data_changes (organization_id, table_name, revision, changed_at)
                VALUES (new_org, TG_TABLE_NAME, 1, clock_timestamp())
                ON CONFLICT (organization_id, table_name) DO UPDATE
                SET revision = platform_data_changes.revision + 1,
                    changed_at = clock_timestamp();
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            target record;
        BEGIN
            FOR target IN
                SELECT table_schema, table_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name = 'organization_id'
                  AND table_name <> 'platform_data_changes'
                GROUP BY table_schema, table_name
            LOOP
                EXECUTE format(
                    'CREATE TRIGGER cestos_track_data_change '
                    'AFTER INSERT OR UPDATE OR DELETE ON %I.%I '
                    'FOR EACH ROW EXECUTE FUNCTION cestos_track_organization_data_change()',
                    target.table_schema,
                    target.table_name
                );
            END LOOP;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            target record;
        BEGIN
            FOR target IN
                SELECT event.table_schema, event.table_name
                FROM information_schema.triggers AS event
                WHERE event.trigger_schema = 'public'
                  AND event.trigger_name = 'cestos_track_data_change'
            LOOP
                EXECUTE format(
                    'DROP TRIGGER IF EXISTS cestos_track_data_change ON %I.%I',
                    target.table_schema,
                    target.table_name
                );
            END LOOP;
        END;
        $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS cestos_track_organization_data_change()")
    op.drop_index("ix_platform_data_changes_org_changed_at", table_name="platform_data_changes")
    op.drop_table("platform_data_changes")

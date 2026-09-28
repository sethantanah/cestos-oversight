"""Ensure the organization data-change feed exists even on previously stamped databases.

Revision ID: 20261017_repair_change_feed
Revises: 20261016_po_desc_nullable
"""

from alembic import op


revision = "20261017_repair_change_feed"
down_revision = "20261016_po_desc_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration may have been skipped after a stale Alembic stamp.
    # Recreate its schema idempotently so an upgrade repairs that state too.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_data_changes (
            organization_id uuid NOT NULL,
            table_name varchar(128) NOT NULL,
            revision bigint NOT NULL DEFAULT 0,
            changed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_platform_data_changes PRIMARY KEY (organization_id, table_name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_platform_data_changes_org_changed_at
        ON platform_data_changes (organization_id, changed_at)
        """
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
        $$
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
                    'DROP TRIGGER IF EXISTS cestos_track_data_change ON %I.%I',
                    target.table_schema,
                    target.table_name
                );
                EXECUTE format(
                    'CREATE TRIGGER cestos_track_data_change '
                    'AFTER INSERT OR UPDATE OR DELETE ON %I.%I '
                    'FOR EACH ROW EXECUTE FUNCTION cestos_track_organization_data_change()',
                    target.table_schema,
                    target.table_name
                );
            END LOOP;
        END;
        $$
        """
    )


def downgrade() -> None:
    pass

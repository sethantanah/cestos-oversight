"""Regression coverage for upgrading document-only notification databases."""

import runpy
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.models.hr import Notification


def test_repair_migration_emits_postgresql_schema_correction():
    migration = runpy.run_path(str(
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20260921_notification_optional.py"
    ))
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration["upgrade"]()
    sql = output.getvalue()
    for name in ("rule_id", "document_id", "expiry_date"):
        assert f"ALTER TABLE notifications ALTER COLUMN {name} DROP NOT NULL" in sql
    assert "ALTER COLUMN message TYPE VARCHAR(1000)" in sql
    assert "DROP CONSTRAINT" not in sql


@pytest.mark.integration
async def test_migrated_database_accepts_arbitrary_domain_events(identities, session_factory):
    user = identities["admin"]
    async with session_factory() as session:
        for domain in ("EQUIPMENT", "INVENTORY", "PROJECTS", "CUSTOM_DOMAIN"):
            # Distinct events must not collide with legacy expiry deduplication.
            rows = [Notification(
                organization_id=user.organization_id,
                recipient_id=user.id,
                message="x" * 1000,
                domain=domain,
            ) for _ in range(2)]
            session.add_all(rows)
            await session.commit()
            ids = [row.id for row in rows]
            session.expunge_all()
            stored = (await session.scalars(
                select(Notification).where(Notification.id.in_(ids))
            )).all()
            assert len(stored) == 2
            for row in stored:
                assert row.rule_id is None
                assert row.document_id is None
                assert row.expiry_date is None
                assert row.schedule_id is None
                assert row.domain == domain
                assert len(row.message) == 1000


def test_migration_graph_has_one_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1

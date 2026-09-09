import subprocess
import sys

from scripts import migrate


def test_run_migrations_recovers_from_stale_alembic_version(monkeypatch):
    upgrade_cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    failure_output = (
        "psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "
        '"pg_type_typname_nsp_index"\n'
        "DETAIL:  Key (typname, typnamespace)=(alembic_version, 2200) already exists."
    )

    results = iter(
        [
            subprocess.CompletedProcess(upgrade_cmd, 1, stdout="", stderr=failure_output),
            subprocess.CompletedProcess(upgrade_cmd, 0, stdout="", stderr=""),
        ]
    )
    recovered = {"value": False}

    def fake_run(cmd, **kwargs):
        assert cmd == upgrade_cmd
        return next(results)

    def fake_recover():
        recovered["value"] = True
        return True

    monkeypatch.setattr(migrate.subprocess, "run", fake_run)
    monkeypatch.setattr(migrate, "recover_stale_alembic_version", fake_recover)

    assert migrate.run_migrations() is True
    assert recovered["value"] is True

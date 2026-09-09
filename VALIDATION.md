# Foundation validation

Verified on 2026-09-07 using Windows, Python 3.14.3, PostgreSQL 18 and the committed uv lockfile.

- Full pytest suite: **17 passed**, including a real Uvicorn subprocess and HTTP readiness check.
- Ruff lint: passed.
- Ruff formatting check: passed (63 Python files).
- Strict mypy: passed (44 application/script source files).
- Alembic initial upgrade, downgrade to base, and upgrade to head: passed on an isolated test database.
- Alembic metadata comparison: **No new upgrade operations detected**.
- Alembic offline upgrade SQL generation: passed.
- Development and test Compose configuration validation: passed using Docker's standalone Compose binary.

The isolated local PostgreSQL cluster used port 55432 and database `cestos_test`. No development database
was used. Its files are ignored by Git and its server was stopped after validation.

Docker Engine was unavailable, so building and running the Docker image could not be verified here.
The Dockerfile targets Python 3.12; runtime tests here used the locally installed Python 3.14.3.
Configure `.env` and administrator credentials using README.md before starting the development stack.

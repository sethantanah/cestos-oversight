import os
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.event_loop import loop_factory
from app.core.security import hash_password
from app.main import create_app
from app.models import Organization, Permission, Role, User

PASSWORD = "Test-only-password-123!"

_TEST_STORAGE = Path(tempfile.mkdtemp(prefix="cestos-test-storage-"))


def pytest_asyncio_loop_factories():
    return {"compatible": loop_factory}


def test_settings(
    url: str = "postgresql+psycopg://unused:unused@localhost/cestos_test",
    storage_dir: str | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=url,
        jwt_secret_key=SecretStr("a-test-only-secret-that-is-over-32-characters"),
        storage_dir=storage_dir or str(_TEST_STORAGE),
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(value)
    development = os.getenv("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        raise ValueError("Tests require a PostgreSQL database with a name ending in _test")
    if development and url.database == make_url(development).database:
        raise ValueError("Test database must differ from the development database")
    env = os.environ.copy()
    env.update(
        DATABASE_URL=value,
        JWT_SECRET_KEY="a-test-only-secret-that-is-over-32-characters",
        APP_ENV="test",
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    return value


@pytest_asyncio.fixture
async def session_factory(database_url: str):
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE audit_logs, refresh_tokens, user_roles, role_permissions, users, "
                "roles, permissions, organizations, business_counters, locations, employees, "
                "employee_documents, skills, employee_skills, clients, projects, "
                "employee_assignments, asset_categories, assets, asset_components, "
                "asset_documents, asset_assignments, asset_meter_readings, departments, "
                "positions, employee_family_members, employee_emergency_contacts, "
                "employee_resumes, employee_qualifications, employee_training_records, "
                "employee_licenses, rotation_patterns, employee_rotations, "
                "employee_asset_authorizations CASCADE"
            )
        )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def identities(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session, session.begin():
        a = Organization(name="Organization A")
        b = Organization(name="Organization B")
        session.add_all([a, b])
        await session.flush()
        read = Permission(code="users.read")
        create = Permission(code="users.create")
        role = Role(name="Reader", organization_id=a.id, permissions=[read, create])
        other_role = Role(name="Reader", organization_id=b.id, permissions=[read])
        password_hash = hash_password(PASSWORD)
        admin = User(
            organization_id=a.id,
            email="admin@example.com",
            password_hash=password_hash,
            first_name="A",
            last_name="Admin",
            roles=[role],
        )
        denied = User(
            organization_id=a.id,
            email="denied@example.com",
            password_hash=password_hash,
            first_name="A",
            last_name="Denied",
            roles=[],
        )
        other = User(
            organization_id=b.id,
            email="admin@example.com",
            password_hash=password_hash,
            first_name="B",
            last_name="Admin",
            roles=[other_role],
        )
        session.add_all([admin, denied, other])
        await session.flush()
        return {"admin": admin, "denied": denied, "other": other}


@pytest_asyncio.fixture
async def client(
    database_url: str, session_factory, identities
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings(database_url))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def login(client: httpx.AsyncClient, user: User) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_id": str(user.organization_id),
            "email": user.email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()

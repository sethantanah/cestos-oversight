import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.security import token_hash
from app.models import AuditLog, Organization, Permission, RefreshToken, Role, User
from app.tests.conftest import PASSWORD, login
from app.tests.conftest import test_settings as make_settings
from scripts.seed import seed

pytestmark = pytest.mark.integration


async def test_database_connectivity(client):
    assert (await client.get("/health/db")).json() == {"status": "ok"}


async def test_login_and_protected_endpoint(client, identities, session_factory):
    tokens = await login(client, identities["admin"])
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(identities["admin"].id)
    assert "password_hash" not in response.text
    async with session_factory() as session:
        stored = await session.scalar(select(RefreshToken))
        assert stored.token_hash == token_hash(tokens["refresh_token"])
        assert stored.token_hash != tokens["refresh_token"]
        assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_invalid_password(client, identities):
    user = identities["admin"]
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_id": str(user.organization_id),
            "email": user.email,
            "password": "wrong",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


async def test_missing_token(client):
    assert (await client.get("/api/v1/users")).status_code == 401


async def test_refresh_rotation_and_logout(client, identities):
    tokens = await login(client, identities["admin"])
    body = {"refresh_token": tokens["refresh_token"]}
    response = await client.post("/api/v1/auth/refresh", json=body)
    assert response.status_code == 200
    assert response.json()["refresh_token"] != tokens["refresh_token"]
    assert (await client.post("/api/v1/auth/refresh", json=body)).status_code == 401
    rotated = {"refresh_token": response.json()["refresh_token"]}
    assert (await client.post("/api/v1/auth/logout", json=rotated)).status_code == 204
    assert (await client.post("/api/v1/auth/logout", json=rotated)).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json=rotated)).status_code == 401


async def test_concurrent_refresh(client, identities):
    tokens = await login(client, identities["admin"])
    results = await asyncio.gather(
        *[
            client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 401]


async def test_permission_denial(client, identities):
    tokens = await login(client, identities["denied"])
    response = await client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 403


async def test_permission_success_and_organization_isolation(client, identities):
    tokens = await login(client, identities["admin"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = await client.get("/api/v1/users", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert all(
        row["organization_id"] == str(identities["admin"].organization_id)
        for row in response.json()["items"]
    )
    assert (
        await client.get(f"/api/v1/users/{identities['other'].id}", headers=headers)
    ).status_code == 404
    other_tokens = await login(client, identities["other"])
    other_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other_tokens['access_token']}"}
    )
    assert other_me.json()["organization_id"] == str(identities["other"].organization_id)


async def test_user_create_conflict_and_audit(client, identities, session_factory):
    tokens = await login(client, identities["admin"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    body = {
        "email": "new@example.com",
        "password": PASSWORD,
        "first_name": "New",
        "last_name": "User",
    }
    response = await client.post("/api/v1/users", json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == str(identities["admin"].organization_id)
    assert (await client.post("/api/v1/users", json=body, headers=headers)).status_code == 409
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == "CREATE")
            )
            == 1
        )


async def test_expired_refresh_and_disabled_user(client, identities, session_factory):
    tokens = await login(client, identities["admin"])
    async with session_factory() as session, session.begin():
        token = await session.scalar(select(RefreshToken))
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        user = await session.get(User, identities["admin"].id)
        user.is_active = False
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401
    assert (
        await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
    ).status_code == 401


async def test_seed_idempotency(session_factory, database_url):
    settings = make_settings(database_url)
    settings.initial_admin_email = "bootstrap@example.com"
    from pydantic import SecretStr

    settings.initial_admin_password = SecretStr(PASSWORD)
    async with session_factory() as session:
        await seed(session, settings)
        counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (Organization, User, Role, Permission)
        ]
        await session.rollback()
        await seed(session, settings)
        assert counts == [
            await session.scalar(select(func.count()).select_from(model))
            for model in (Organization, User, Role, Permission)
        ]


async def test_database_constraints(session_factory, identities):
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) "
                        "SELECT user_id, role_id FROM user_roles LIMIT 1"
                    )
                )

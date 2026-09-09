import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import create_app
from app.tests.conftest import test_settings as make_settings


async def test_health() -> None:
    app = create_app(make_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
        assert response.json() == {"status": "ok"}
        uuid.UUID(response.headers["x-request-id"])
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        error = await client.post("/api/v1/auth/login", json={"password": "secret"})
        assert error.status_code == 422
        assert "secret" not in error.text
    await app.state.engine.dispose()


def test_password_hashing() -> None:
    hashed = hash_password("a-test-password")
    assert hashed.startswith("$argon2")
    assert verify_password("a-test-password", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_validation() -> None:
    settings = make_settings()
    user, organization = uuid.uuid4(), uuid.uuid4()
    token = create_access_token(user, organization, settings)
    assert decode_access_token(token, settings)["org"] == str(organization)
    with pytest.raises(AuthenticationError):
        decode_access_token(token + "bad", settings)
    payload = decode_access_token(token, settings)
    payload["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    expired = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(expired, settings)


def test_sqlite_and_placeholder_secrets_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///test.db", jwt_secret_key="x" * 40)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=make_settings().database_url,
            jwt_secret_key="replace-with-at-least-32-random-characters",
        )

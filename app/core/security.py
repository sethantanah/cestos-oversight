import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.exceptions import AuthenticationError

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_access_token(
    user_id: uuid.UUID, organization_id: uuid.UUID, settings: Settings, token_version: int = 0
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "org": str(organization_id),
            "type": "access",
            "ver": token_version,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
            "jti": str(uuid.uuid4()),
            "iss": "cestos",
            "aud": "cestos-api",
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(raw: str, settings: Settings) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            raw,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer="cestos",
            audience="cestos-api",
            options={"require": ["sub", "org", "type", "iat", "exp", "jti"]},
        )
        if payload["type"] != "access":
            raise ValueError("Wrong token type")
        uuid.UUID(payload["sub"])
        uuid.UUID(payload["org"])
        return payload
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
        raise AuthenticationError("Invalid or expired access token") from exc

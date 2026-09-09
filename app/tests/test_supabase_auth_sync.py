import uuid

from app.core.config import Settings
from app.models.user import User
from app.services.supabase_auth import SupabaseAuthSyncService


def test_supabase_auth_sync_creates_user_and_tracks_id(monkeypatch):
    captured = {}

    class FakeUserResponse:
        class user:
            id = "supabase-user-123"

    class FakeAdmin:
        def create_user(self, payload):
            captured["create"] = payload
            return FakeUserResponse()

        def update_user_by_id(self, uid, payload):
            captured["update"] = (uid, payload)
            return FakeUserResponse()

    class FakeAuth:
        admin = FakeAdmin()

    class FakeClient:
        auth = FakeAuth()

    monkeypatch.setattr(
        "app.services.supabase_auth.create_client",
        lambda url, key: FakeClient(),
    )

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://user:pass@localhost:5432/cestos_prod",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        supabase_auth_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key",
    )

    user = User(
        organization_id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hashed-password",
        first_name="Ada",
        last_name="Lovelace",
    )

    result = SupabaseAuthSyncService(settings).sync_user(user, password="StrongPass123!")

    assert result == "supabase-user-123"
    assert user.supabase_user_id == "supabase-user-123"
    assert captured["create"]["email"] == "user@example.com"
    assert captured["create"]["user_metadata"]["app_user_id"] == str(user.id)


def test_supabase_auth_sync_is_noop_when_disabled():
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://user:pass@localhost:5432/cestos_prod",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        supabase_auth_enabled=False,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key",
    )

    user = User(
        organization_id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hashed-password",
        first_name="Ada",
        last_name="Lovelace",
    )

    assert SupabaseAuthSyncService(settings).sync_user(user, password="StrongPass123!") is None
    assert user.supabase_user_id is None

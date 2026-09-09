import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.storage import LocalStorage, SupabaseStorage, build_storage


def test_build_storage_uses_supabase_in_production(monkeypatch):
    import app.core.storage as storage_module

    monkeypatch.setattr(storage_module, "create_client", lambda *args, **kwargs: object())

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://user:pass@localhost:5432/cestos_prod",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        storage_provider="supabase",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-key",
    )

    adapter = build_storage(settings)
    assert isinstance(adapter, SupabaseStorage)


def test_build_storage_falls_back_to_local_for_non_production():
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+psycopg://user:pass@localhost:5432/cestos_dev",
        jwt_secret_key="a-test-only-secret-that-is-over-32-characters",
        storage_provider="local",
    )

    adapter = build_storage(settings)
    assert isinstance(adapter, LocalStorage)


def test_production_rejects_local_storage():
    with pytest.raises(ValidationError, match="local storage is not allowed"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://user:pass@localhost:5432/cestos_prod",
            jwt_secret_key="x" * 40,
            app_env="production",
            storage_provider="local",
        )

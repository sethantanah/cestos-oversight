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


@pytest.mark.parametrize("existing_documents", [False, True])
def test_supabase_document_upload_passes_bucket_options_by_keyword(monkeypatch, existing_documents):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import app.core.storage as storage_module

    names = {"uploads-documents"} if existing_documents else set()
    calls = []
    bucket = Mock()

    # Match the SDK's optional name argument: a positional options dict is invalid.
    def create_bucket(identifier, name=None, options=None):
        assert name is None or isinstance(name, str)
        assert options is not None
        calls.append(("create", identifier, options))
        names.add(identifier)

    def update_bucket(identifier, name=None, options=None):
        assert name is None or isinstance(name, str)
        assert options == {"public": False}
        calls.append(("update", identifier, options))

    client = SimpleNamespace(storage=SimpleNamespace(
        list_buckets=lambda: [{"name": name} for name in names],
        create_bucket=create_bucket, update_bucket=update_bucket,
        from_=Mock(return_value=bucket),
    ))
    monkeypatch.setattr(storage_module, "create_client", lambda *args: client)
    adapter = SupabaseStorage("https://example.supabase.co", "test-key", "uploads", 1024)
    stored = adapter.save("documents/test", b"example", "evidence.pdf", "application/pdf")
    assert ("create", "uploads", {"public": True}) in calls
    assert ("update" if existing_documents else "create", "uploads-documents", {"public": False}) in calls
    client.storage.from_.assert_called_with("uploads-documents")
    bucket.upload.assert_called_once_with(stored.relative_path, b"example", {"content-type": "application/pdf", "upsert": "true"})
    adapter.private_bucket()
    assert len(calls) == 2

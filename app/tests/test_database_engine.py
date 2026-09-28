from types import SimpleNamespace

import pytest

from app.core import database


@pytest.mark.parametrize(
    ("url", "expected_argument"),
    [
        ("postgresql+psycopg://user:pass@localhost/app", "prepare_threshold"),
        ("postgresql+asyncpg://user:pass@localhost/app", "prepared_statement_cache_size"),
    ],
)
def test_build_engine_disables_session_cached_prepared_statements(
    monkeypatch, url: str, expected_argument: str
) -> None:
    captured = {}

    def fake_create_async_engine(database_url, **kwargs):
        captured["url"] = database_url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)

    database.build_engine(SimpleNamespace(database_url=url))

    assert captured["connect_args"][expected_argument] in (None, 0)
    if url.startswith("postgresql+asyncpg://"):
        assert captured["connect_args"]["prepared_statement_name_func"]().startswith(
            "__asyncpg_"
        )

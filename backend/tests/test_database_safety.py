"""Чистые проверки: опасный адрес БД отклоняется до подключения и миграций."""

import pytest

from tests.conftest import validate_test_database_url


@pytest.mark.parametrize(
    "url",
    [None, "postgresql+psycopg://localhost/cashcast", "sqlite:///cashcast_test"],
)
def test_rejects_non_test_database(url: str | None) -> None:
    with pytest.raises(pytest.UsageError):
        validate_test_database_url(url)


def test_accepts_explicit_postgres_test_database() -> None:
    url = "postgresql+psycopg://localhost/cashcast_test"
    assert validate_test_database_url(url) == url


@pytest.mark.parametrize("fail", [False, True])
def test_migration_replaces_cached_settings_and_restores_environment(monkeypatch, fail):
    from alembic import command

    from app.core.config import get_settings
    from tests.conftest import _migrate

    original = "postgresql+psycopg://localhost/application"
    target = "postgresql+psycopg://localhost/cashcast_test"
    monkeypatch.setenv("CC_DATABASE_URL", original)
    get_settings.cache_clear()
    assert get_settings().database_url == original

    def upgrade(config, revision):
        # Подключений нет: проверяем адрес, который прочитал бы Alembic.
        assert get_settings().database_url == target
        if fail:
            raise RuntimeError("migration failed")

    monkeypatch.setattr(command, "upgrade", upgrade)
    migration = _migrate.__wrapped__(target)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="migration failed"):
                next(migration)
        else:
            next(migration)
            migration.close()
        assert get_settings().database_url == original
    finally:
        get_settings.cache_clear()

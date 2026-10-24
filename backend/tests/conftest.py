"""Фикстуры тестов: отдельный PostgreSQL только по CC_TEST_DATABASE_URL и клиент API.

Чистые тесты не запускают миграции; интеграционные требуют явную тестовую БД.
Схема создаётся через Alembic (migrations up) — проверяем ровно то, что поедет в прод.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def validate_test_database_url(value: str | None) -> str:
    """Не позволяем миграциям и очистке тестов затронуть обычную БД."""
    from sqlalchemy.engine import make_url

    if not value:
        raise pytest.UsageError("Задайте CC_TEST_DATABASE_URL на отдельную БД с суффиксом _test")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_test"):
        raise pytest.UsageError("Тесты разрешены только на PostgreSQL БД с суффиксом _test")
    return value


@pytest.fixture(scope="session")
def database_url() -> str:
    return validate_test_database_url(os.environ.get("CC_TEST_DATABASE_URL"))


@pytest.fixture(scope="session")
def _migrate(database_url: str) -> Iterator[None]:
    # Прогоняем Alembic до head на тестовой БД один раз за сессию.
    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings

    previous = os.environ.get("CC_DATABASE_URL")
    os.environ["CC_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        yield
    finally:
        # Возвращаем окружение даже при ошибке миграции; старый кэш не сохраняем.
        if previous is None:
            os.environ.pop("CC_DATABASE_URL", None)
        else:
            os.environ["CC_DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture
def engine(database_url: str, _migrate):
    eng = create_engine(database_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    # Чистые вычислительные тесты не запрашивают engine и не зависят от PostgreSQL.
    if "engine" not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue("engine")
    yield
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()
    # Подменяем фабрику сессий из lifespan на тестовую (тот же движок).
    app.state.session_factory = session_factory
    with TestClient(app) as c:
        # TestClient запускает lifespan; он перезапишет session_factory своим движком,
        # поэтому ставим нашу после входа в контекст.
        app.state.session_factory = session_factory
        yield c

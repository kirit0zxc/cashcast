"""Фикстуры тестов: локальный PostgreSQL через pgserver (без Docker) и клиент API.

В CI вместо pgserver берётся сервис postgres: если задан CC_DATABASE_URL, используем его.
Схема создаётся через Alembic (migrations up) — проверяем ровно то, что поедет в прод.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    external = os.environ.get("CC_DATABASE_URL")
    if external:
        # CI: Postgres уже поднят сервисом.
        yield external
        return
    # Локально: портативный Postgres в temp-каталоге, без установки и Docker.
    import pgserver

    data_dir = tmp_path_factory.mktemp("pgdata")
    srv = pgserver.get_server(str(data_dir), cleanup_mode="stop")
    srv.psql("CREATE DATABASE cashcast;")
    base = srv.get_uri()  # postgresql://postgres:@127.0.0.1:PORT/postgres
    uri = base.rsplit("/", 1)[0] + "/cashcast"
    # Драйвер psycopg3 для SQLAlchemy.
    uri = uri.replace("postgresql://", "postgresql+psycopg://")
    try:
        yield uri
    finally:
        srv.cleanup()


@pytest.fixture(scope="session", autouse=True)
def _migrate(database_url: str) -> None:
    # Прогоняем Alembic до head на тестовой БД один раз за сессию.
    os.environ["CC_DATABASE_URL"] = database_url
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture
def engine(database_url: str):
    eng = create_engine(database_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_tables(engine) -> Iterator[None]:
    # Каждый тест на чистых данных: усечь все таблицы, кроме alembic_version.
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

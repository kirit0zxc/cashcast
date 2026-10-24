"""Зависимости FastAPI: движок, фабрика сессий и сессия БД на запрос.

Движок создаётся один раз в lifespan приложения и кладётся в app.state.
get_db берёт фабрику оттуда — тесты подменяют app.state.session_factory на свою.
Все HTTP-потребители используют scope="function": commit обязан завершиться до
отправки ответа, иначе немедленное чтение нового job/import может получить404.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

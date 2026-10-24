"""Подключение к PostgreSQL. Синхронный SQLAlchemy: проще транзакции и тесты, нагрузки для async нет."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping спасает от «мёртвых» соединений после рестарта postgres в Compose.
    return create_engine(database_url, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: после commit объекты можно сериализовать в ответ без лишнего SELECT.
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise

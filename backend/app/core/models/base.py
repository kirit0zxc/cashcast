"""Базовый класс ORM и общие типы колонок.

Деньги везде — целые копейки (BIGINT, *_minor) + отдельное направление in/out.
float для денег запрещён: 0.1 + 0.2 != 0.3 ломает сверку остатков.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Явные имена ограничений: Alembic генерирует стабильные миграции, а ошибки читаемы.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


# MVP работает только с рублями: курсы не выдумываем, другие валюты отклоняем явно.
SUPPORTED_CURRENCIES = frozenset({"RUB"})

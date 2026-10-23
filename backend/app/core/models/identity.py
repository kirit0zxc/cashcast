"""Пользователи, сессии, компании, членство и банковские счета."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base, created_at_col, uuid_pk


class User(Base):
    __tablename__ = "app_user"  # "user" — зарезервированное слово PostgreSQL

    id: Mapped[uuid.UUID] = uuid_pk()
    # Email храним в нижнем регистре — уникальность без учёта регистра обеспечивает код входа.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class UserSession(Base):
    """Серверная сессия: токен из HttpOnly cookie, хранится только хеш. Выход = удаление строки."""

    __tablename__ = "user_session"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # CSRF-токен привязан к сессии (double submit: cookie + заголовок должны совпасть с этим).
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Company(Base):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class CompanyMember(Base):
    """Доступ пользователя к компании. Все запросы к данным фильтруются через эту таблицу."""

    __tablename__ = "company_member"
    __table_args__ = (CheckConstraint("role IN ('owner', 'viewer')", name="role"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
    created_at: Mapped[datetime] = created_at_col()


class Account(Base):
    """Банковский счёт компании. Прогноз строится по счёту (консолидация — позже, см. план)."""

    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_account_company_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    # Только маска вида «•• 1234»: полные реквизиты сервису не нужны.
    number_mask: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_col()

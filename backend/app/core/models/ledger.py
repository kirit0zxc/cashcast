"""Импорт выписок, операции и дневные остатки."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base, created_at_col, uuid_pk


class StatementImport(Base):
    """Загруженный файл выписки. Таблица названа statement_import: IMPORT — ключевое слово SQL."""

    __tablename__ = "statement_import"
    __table_args__ = (
        # Повторная загрузка того же файла в тот же счёт возвращает существующий импорт.
        UniqueConstraint("account_id", "content_sha256", name="uq_statement_import_account_sha"),
        CheckConstraint("status IN ('previewed', 'committed', 'failed')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Исходный файл храним в БД (закрытый volume postgres): нужен для повторного разбора
    # после смены маппинга колонок и для аудита. Наружу и в логи не отдаём.
    raw_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="previewed")
    # Сводка разбора и коммита (кол-во строк, ошибок, дублей) — без содержимого строк.
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = created_at_col()
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankTransaction(Base):
    """Фактическая операция по счёту. Таблица bank_transaction: TRANSACTION — ключевое слово SQL."""

    __tablename__ = "bank_transaction"
    __table_args__ = (
        # Идемпотентность импорта: один отпечаток операции на счёт.
        UniqueConstraint("account_id", "fingerprint", name="uq_bank_transaction_account_fp"),
        CheckConstraint("amount_minor >= 0", name="amount_non_negative"),
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        CheckConstraint(
            "category_source IS NULL OR category_source IN ('auto', 'manual')",
            name="category_source",
        ),
        Index("ix_bank_transaction_account_booked", "account_id", "booked_on"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statement_import.id", ondelete="SET NULL")
    )
    source_row: Mapped[int | None] = mapped_column(Integer)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    counterparty_name: Mapped[str | None] = mapped_column(String(500))
    # Нормализованный ключ контрагента (ИНН или очищенное имя) — для регулярностей и сверки.
    counterparty_ref: Mapped[str | None] = mapped_column(String(200))
    purpose: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(200))
    # ext:<id> если банк дал ID операции, иначе хеш полей + номер повтора внутри файла.
    fingerprint: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    category_source: Mapped[str | None] = mapped_column(String(10))
    category_reason: Mapped[str | None] = mapped_column(String(500))
    category_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()


class DailyBalance(Base):
    """Остаток на конец дня. Отдельно от операций: повторённое в каждой строке значение не суммируем."""

    __tablename__ = "daily_balance"
    __table_args__ = (
        UniqueConstraint("account_id", "balance_date", name="uq_daily_balance_account_date"),
        CheckConstraint("source IN ('statement', 'manual')", name="source"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Остаток может быть отрицательным (овердрафт) — знак хранится в самом числе.
    closing_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="statement")
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statement_import.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()

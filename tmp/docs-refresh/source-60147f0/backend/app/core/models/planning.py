"""Плановые события (счета, обязательства, ручные события) и их связь с фактом."""

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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base, created_at_col, uuid_pk

PLANNED_EVENT_STATUSES = ("planned", "partially_paid", "paid", "cancelled")
PLANNED_EVENT_KINDS = ("invoice", "obligation", "tax", "manual", "recurring")
PLANNED_EVENT_SOURCES = ("manual", "csv", "recurrence")


class PlannedEvent(Base):
    __tablename__ = "planned_event"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "remaining_amount_minor >= 0 AND remaining_amount_minor <= amount_minor",
            name="remaining_range",
        ),
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        CheckConstraint(f"status IN {PLANNED_EVENT_STATUSES}", name="status"),
        CheckConstraint(f"kind IN {PLANNED_EVENT_KINDS}", name="kind"),
        CheckConstraint(f"source IN {PLANNED_EVENT_SOURCES}", name="source"),
        # Один внешний документ (счёт из CSV, договор) = одно событие; повторный импорт не дублирует.
        Index(
            "uq_planned_event_source_ref",
            "company_id",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
        Index("ix_planned_event_company_due", "company_id", "due_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = событие компании без привязки к счёту (тогда в прогноз счёта не попадает).
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL")
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Частичная оплата уменьшает остаток обязательства, а не создаёт второе событие.
    remaining_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200))
    # Когда событие стало известно. Нужен честному backtest: будущее знание не подмешиваем.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    counterparty_name: Mapped[str | None] = mapped_column(String(500))
    counterparty_ref: Mapped[str | None] = mapped_column(String(256))
    provenance: Mapped[str | None] = mapped_column(Text)
    tax_regime: Mapped[str | None] = mapped_column(Text)
    # Первоначальный документ не меняется при ручной правке/оплате события.
    source_payload: Mapped[dict | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(50))
    recurrence_group: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlannedEventMatch(Base):
    """Связь планового события с фактической операцией (план-факт).

    candidate — найдено автоматически, ждёт подтверждения; confirmed — учтено в остатке события.
    """

    __tablename__ = "planned_event_match"
    __table_args__ = (
        UniqueConstraint("planned_event_id", "transaction_id", name="uq_planned_event_match_pair"),
        CheckConstraint("matched_amount_minor > 0", name="amount_positive"),
        CheckConstraint("status IN ('candidate', 'confirmed', 'rejected')", name="status"),
        CheckConstraint("method IN ('auto', 'manual')", name="method"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    planned_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planned_event.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_transaction.id", ondelete="CASCADE"), nullable=False
    )
    matched_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="auto")
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_col()

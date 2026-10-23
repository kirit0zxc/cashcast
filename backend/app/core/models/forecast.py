"""Снимки прогнозов, их точки и очередь заданий."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import Base, created_at_col, uuid_pk

RUN_STATUSES = ("pending", "running", "succeeded", "failed")


class ForecastRun(Base):
    """Неизменяемый снимок прогноза: что считали, на каких данных и какой моделью."""

    __tablename__ = "forecast_run"
    __table_args__ = (
        # Одинаковый вход + модель + seed + сценарий = один результат (повторный запрос не плодит копии).
        UniqueConstraint(
            "account_id",
            "as_of",
            "horizon_days",
            "data_version",
            "model_version",
            "seed",
            "scenario_hash",
            name="uq_forecast_run_input_version",
        ),
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint("horizon_days > 0", name="horizon_positive"),
        CheckConstraint(
            "probability_any_negative IS NULL OR "
            "(probability_any_negative >= 0 AND probability_any_negative <= 1)",
            name="probability_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # sha256 входных данных (операции, остатки, плановые события) на момент запроса.
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    # Пустая строка = базовый прогноз; для сценария — хеш изменений.
    scenario_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    base_forecast_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_run.id", ondelete="CASCADE")
    )
    scenario: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    opening_balance_minor: Mapped[int | None] = mapped_column(BigInteger)
    assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Риск: дата первого минуса и дефицит — по медианной траектории; вероятность — на горизонте.
    risk_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_negative_date: Mapped[date | None] = mapped_column(Date)
    max_deficit_minor: Mapped[int | None] = mapped_column(BigInteger)
    probability_any_negative: Mapped[float | None] = mapped_column(Float)
    # Вклад компонентов и связанные события — для ручки explanations (структура у Данила/Димы).
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Только enqueue заполняет снимок; worker/scenario используют его без чтения новых фактов.
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ForecastPoint(Base):
    __tablename__ = "forecast_point"
    __table_args__ = (
        CheckConstraint("inflow_minor >= 0 AND outflow_minor >= 0", name="flows_non_negative"),
        CheckConstraint(
            "probability_negative IS NULL OR (probability_negative >= 0 AND probability_negative <= 1)",
            name="probability_range",
        ),
    )

    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_run.id", ondelete="CASCADE"), primary_key=True
    )
    point_date: Mapped[date] = mapped_column(Date, primary_key=True)
    inflow_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outflow_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_p10_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_p50_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_p90_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Доля траекторий с минусом в этот день; NULL, если модель неопределённость не оценивает.
    probability_negative: Mapped[float | None] = mapped_column(Float)


JOB_STATUSES = ("pending", "running", "succeeded", "failed")


class Job(Base):
    """Задание фонового worker. Очередь в PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED + lease."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="status"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0", name="attempts"),
        Index("ix_job_status_run_after", "status", "run_after"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Ключ от двойной постановки одного и того же расчёта (например, forecast_run:<id>).
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    # Только код/тип ошибки, без текста исключения — там могут быть данные клиента.
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Общие контракты модулей расчёта — чистый Python без HTTP и без SQLAlchemy.

Это граница между интегратором (backend) и аналитикой (Данил, Дима).
DTO здесь — единственный разрешённый способ передавать данные в модули и обратно.
Деньги — всегда int копеек. Даты — datetime.date. Никакого float для сумм.

Реализации живут в:
  - modules/categorization/  (Дима)  — Categorizer
  - modules/planning/        (Дима)  — RecurrenceDetector, PlannedEventMatcher
  - modules/forecasting/     (Данил) — ForecastService
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


# ----------------------------------------------------------------------------
# Вход: операции и остатки (снимок данных готовит backend из БД)
# ----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TxnDTO:
    id: str
    account_id: str
    booked_on: date
    amount_minor: int
    direction: Direction
    currency: str = "RUB"
    counterparty_name: str | None = None
    counterparty_ref: str | None = None
    purpose: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class DailyBalanceDTO:
    account_id: str
    balance_date: date
    closing_balance_minor: int


# ----------------------------------------------------------------------------
# Категоризация (Дима)
# ----------------------------------------------------------------------------
# Единый словарь категорий проекта. Неизвестное — OTHER, не угадывать.
class Category(StrEnum):
    SALES = "sales"
    PURCHASES = "purchases"
    PAYROLL = "payroll"
    RENT = "rent"
    TAX = "tax"
    FEES = "fees"
    LOAN = "loan"
    TRANSFER = "transfer"  # внутренний перевод между своими счетами
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CategoryAssignment:
    transaction_id: str
    category: Category
    # Почему так классифицировано (правило/контрагент) — показывается пользователю.
    reason: str
    confidence: float  # 0..1; низкое говорит фронту предложить ручную правку


class Categorizer(Protocol):
    def categorize(self, txns: list[TxnDTO]) -> list[CategoryAssignment]: ...


# ----------------------------------------------------------------------------
# Регулярности (Дима)
# ----------------------------------------------------------------------------
class RecurrenceInterval(StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"  # календарный месяц; платёж последнего дня не сдвигаем на фикс. 30 дней
    QUARTERLY = "quarterly"


@dataclass(frozen=True, slots=True)
class RecurrenceGroup:
    group_id: str
    direction: Direction
    interval: RecurrenceInterval
    typical_amount_minor: int
    counterparty_ref: str | None
    category: Category | None
    confidence: float
    member_transaction_ids: list[str]
    next_expected_date: date | None
    reason: str


class RecurrenceDetector(Protocol):
    # as_of: правила ищем только по прошлому относительно этой даты (без утечки будущего).
    def detect(self, txns: list[TxnDTO], as_of: date) -> list[RecurrenceGroup]: ...


# ----------------------------------------------------------------------------
# Плановые события и сопоставление план/факт (Дима)
# ----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PlannedEventDTO:
    id: str
    direction: Direction
    amount_minor: int
    remaining_amount_minor: int
    due_date: date
    status: str
    kind: str
    source: str
    available_at: date
    counterparty_ref: str | None = None
    recurrence_group: str | None = None


@dataclass(frozen=True, slots=True)
class MatchProposal:
    planned_event_id: str
    transaction_id: str
    matched_amount_minor: int
    confidence: float
    reason: str
    # True — однозначно, можно подтвердить автоматически; False — кандидат, нужен человек.
    auto_confirm: bool


class PlannedEventMatcher(Protocol):
    # Не допускает двойного счёта: закрытый счёт не остаётся ещё и ожидаемым событием.
    def match(
        self, planned: list[PlannedEventDTO], txns: list[TxnDTO]
    ) -> list[MatchProposal]: ...


# ----------------------------------------------------------------------------
# Прогноз и риск (Данил)
# ----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ScenarioChange:
    """Одно изменение сценария «что если». Не меняет фактические операции."""

    kind: str  # delay_event | reduce_irregular_inflow | add_expense | increase_recurring
    target_id: str | None = None
    shift_days: int | None = None
    factor: float | None = None  # для снижения выручки: 0.7 = -30%
    amount_minor: int | None = None
    on_date: date | None = None


@dataclass(frozen=True, slots=True)
class ForecastInput:
    account_id: str
    as_of: date
    horizon_days: int
    opening_balance_minor: int
    seed: int
    txns: list[TxnDTO]
    daily_balances: list[DailyBalanceDTO]
    planned_events: list[PlannedEventDTO]
    recurrences: list[RecurrenceGroup] = field(default_factory=list)
    scenario: list[ScenarioChange] = field(default_factory=list)
    data_version: str = ""


@dataclass(frozen=True, slots=True)
class ForecastPointDTO:
    point_date: date
    inflow_minor: int
    outflow_minor: int
    balance_p10_minor: int
    balance_p50_minor: int
    balance_p90_minor: int
    probability_negative: float | None  # доля траекторий с минусом в этот день


@dataclass(frozen=True, slots=True)
class RiskSummary:
    # Все поля опциональны: при короткой истории риск недоступен, показываем план без вероятности.
    available: bool
    first_negative_date: date | None = None
    max_deficit_minor: int | None = None
    # Вероятность хотя бы одного минуса за весь горизонт — отдельно от дневной.
    probability_any_negative: float | None = None
    related_event_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    model_version: str
    points: list[ForecastPointDTO]
    risk: RiskSummary
    assumptions: list[str] = field(default_factory=list)
    data_warnings: list[str] = field(default_factory=list)
    # Вклад компонентов (регулярности, события, остаточный поток) для ручки explanations.
    details: dict = field(default_factory=dict)


class ForecastService(Protocol):
    def run(self, data: ForecastInput) -> ForecastResult: ...

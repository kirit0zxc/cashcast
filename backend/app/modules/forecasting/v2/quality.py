"""Явная валидация и причинный отчёт пригодности; реальные суммы не исправляются."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, fields, replace
from datetime import date, timedelta

from app.modules.contracts import (
    DailyBalanceDTO,
    Direction,
    ForecastInput,
    PlannedEventDTO,
    RecurrenceGroup,
    RecurrenceInterval,
    ScenarioChange,
    TxnDTO,
)

MAX_MONEY_MINOR = 9_000_000_000_000_000


class ForecastInputError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ResourceLimits:
    transactions: int = 50_000
    balances: int = 4_000
    events: int = 2_000
    recurrences: int = 2_000
    scenario_changes: int = 50
    text_characters: int = 8_000_000


@dataclass(frozen=True)
class QualityReport:
    policy_version: str
    mode: str
    history_days: int
    training_start: date
    last_balance_age_days: int | None
    reconciliation_breaks: int
    unobserved_calendar_days: int
    eligible_for_simulation: bool
    eligible_for_probability: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "mode": self.mode,
            "history_days": self.history_days,
            "training_start": self.training_start.isoformat(),
            "last_balance_age_days": self.last_balance_age_days,
            "reconciliation_breaks": self.reconciliation_breaks,
            "unobserved_calendar_days": self.unobserved_calendar_days,
            "eligible_for_simulation": self.eligible_for_simulation,
            "eligible_for_probability": self.eligible_for_probability,
            "warnings": list(self.warnings),
        }


def _integer(value, label: str, *, nonnegative: bool = False) -> None:
    if type(value) is not int or abs(value) > MAX_MONEY_MINOR or (nonnegative and value < 0):
        raise ForecastInputError("invalid_forecast_input", f"Некорректное целое поле {label}")


def _date(value, label: str) -> None:
    if type(value) is not date:
        raise ForecastInputError("invalid_forecast_input", f"Некорректная дата {label}")


def _identifier(value, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ForecastInputError("invalid_forecast_input", f"Некорректный идентификатор {label}")


def _optional_text(value) -> None:
    if value is not None and not isinstance(value, str):
        raise ForecastInputError("invalid_forecast_input", "Текстовое поле должно быть строкой или None")


def _check_text_budget(data: ForecastInput, maximum: int) -> None:
    stack = [(data, 0)]
    text_size = nodes = 0
    kinds = (ForecastInput, TxnDTO, DailyBalanceDTO, PlannedEventDTO, RecurrenceGroup, ScenarioChange)
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 1_000_000:
            raise ForecastInputError("forecast_resource_limit", "Превышен предел вложенных элементов")
        if isinstance(value, str):
            text_size += len(value)
            if text_size > maximum:
                raise ForecastInputError("forecast_resource_limit", "Превышен общий предел текстовых данных")
        elif isinstance(value, kinds):
            stack.extend((getattr(value, field.name), depth + 1) for field in fields(value))
        elif isinstance(value, (list, tuple)):
            if len(value) > 50_000 or len(stack) + len(value) > 100_000:
                raise ForecastInputError("forecast_resource_limit", "Превышен предел вложенной коллекции")
            stack.extend((item, depth + 1) for item in value)
        elif value is not None and not isinstance(value, (int, float, date)):
            raise ForecastInputError("invalid_forecast_input", "Неподдерживаемый вложенный тип")


def validate_input(data: ForecastInput, limits: ResourceLimits = ResourceLimits()) -> ForecastInput:
    if not isinstance(data, ForecastInput):
        raise ForecastInputError("invalid_forecast_input", "Ожидается ForecastInput")
    _date(data.as_of, "as_of")
    if not date.min + timedelta(days=366) <= data.as_of <= date.max - timedelta(days=180):
        raise ForecastInputError("invalid_forecast_input", "as_of вне безопасного календарного диапазона")
    _identifier(data.account_id, "account_id")
    _integer(data.opening_balance_minor, "opening_balance_minor")
    if type(data.horizon_days) is not int or not 1 <= data.horizon_days <= 180:
        raise ForecastInputError("invalid_forecast_input", "Поддерживается горизонт1–180 календарных дней")
    if type(data.seed) is not int or not -(2**63) <= data.seed < 2**63:
        raise ForecastInputError("invalid_forecast_input", "seed должен быть целым signed64")
    for field, maximum in (
        ("txns", limits.transactions),
        ("daily_balances", limits.balances),
        ("planned_events", limits.events),
        ("recurrences", limits.recurrences),
        ("scenario", limits.scenario_changes),
    ):
        values = getattr(data, field)
        if not isinstance(values, (list, tuple)) or len(values) > maximum:
            raise ForecastInputError("forecast_resource_limit", f"Превышен предел {field}")
    for field, kind in (
        ("txns", TxnDTO),
        ("daily_balances", DailyBalanceDTO),
        ("planned_events", PlannedEventDTO),
        ("recurrences", RecurrenceGroup),
        ("scenario", ScenarioChange),
    ):
        if any(not isinstance(value, kind) for value in getattr(data, field)):
            raise ForecastInputError("invalid_forecast_input", f"Неверный тип элемента {field}")
    # Размер входа ограничивается до сортировок/симуляции; содержимое полей не логируется.
    _check_text_budget(data, limits.text_characters)
    for txn in data.txns:
        _date(txn.booked_on, "booked_on")
        for value in (txn.purpose, txn.counterparty_name, txn.counterparty_ref, txn.category):
            _optional_text(value)
    txns = [txn for txn in data.txns if txn.account_id == data.account_id and txn.booked_on <= data.as_of]
    seen = set()
    for txn in txns:
        _identifier(txn.id, "transaction_id")
        _integer(txn.amount_minor, "amount_minor", nonnegative=True)
        if (
            txn.currency != "RUB"
            or not isinstance(txn.direction, str)
            or txn.direction not in {Direction.IN, Direction.OUT}
        ):
            raise ForecastInputError("invalid_forecast_input", "Поддерживается только RUB и direction in/out")
        if txn.id in seen:
            raise ForecastInputError("invalid_forecast_input", "Повторный transaction_id")
        seen.add(txn.id)
    txns.sort(key=lambda txn: (txn.booked_on, txn.id))
    if sum(txn.amount_minor for txn in txns) > MAX_MONEY_MINOR:
        raise ForecastInputError("forecast_resource_limit", "Превышен денежный бюджет истории")
    for balance in data.daily_balances:
        _date(balance.balance_date, "balance_date")
    balances = sorted(
        (
            balance
            for balance in data.daily_balances
            if balance.account_id == data.account_id and balance.balance_date <= data.as_of
        ),
        key=lambda balance: balance.balance_date,
    )
    seen_days = set()
    for balance in balances:
        _integer(balance.closing_balance_minor, "closing_balance_minor")
        if balance.balance_date in seen_days:
            raise ForecastInputError("invalid_forecast_input", "Неоднозначный остаток одной даты")
        seen_days.add(balance.balance_date)
    events = []
    seen_events = set()
    for event in data.planned_events:
        _date(event.available_at, "available_at")
        if event.available_at > data.as_of:
            continue
        _date(event.due_date, "due_date")
        _identifier(event.id, "event_id")
        _integer(event.amount_minor, "event.amount_minor", nonnegative=True)
        _integer(event.remaining_amount_minor, "remaining_amount_minor", nonnegative=True)
        if (
            event.remaining_amount_minor > event.amount_minor
            or event.id in seen_events
            or not isinstance(event.direction, str)
            or event.direction not in {Direction.IN, Direction.OUT}
            or not isinstance(event.status, str)
            or event.status not in {"planned", "partially_paid", "paid", "cancelled"}
            or (event.status == "paid" and event.remaining_amount_minor != 0)
        ):
            raise ForecastInputError("invalid_forecast_input", "Некорректное состояние планового события")
        seen_events.add(event.id)
        for value in (event.counterparty_ref, event.recurrence_group):
            _optional_text(value)
        for value in (event.kind, event.source):
            _identifier(value, "event.kind/source")
        events.append(event)
    if sum(event.remaining_amount_minor for event in events) > MAX_MONEY_MINOR:
        raise ForecastInputError("forecast_resource_limit", "Превышен денежный бюджет планов")
    for group in data.recurrences:
        _identifier(group.group_id, "group_id")
        _integer(group.typical_amount_minor, "typical_amount_minor", nonnegative=True)
        if (
            not isinstance(group.direction, str)
            or group.direction not in {Direction.IN, Direction.OUT}
            or not isinstance(group.interval, str)
            or group.interval not in set(RecurrenceInterval)
            or type(group.confidence) not in (int, float)
            or not math.isfinite(group.confidence)
            or not 0 <= group.confidence <= 1
            or not isinstance(group.member_transaction_ids, (list, tuple))
        ):
            raise ForecastInputError("invalid_forecast_input", "Некорректная регулярность")
        for member_id in group.member_transaction_ids:
            _identifier(member_id, "member_transaction_id")
        for value in (group.reason, group.counterparty_ref, group.category):
            _optional_text(value)
        if group.next_expected_date is not None:
            _date(group.next_expected_date, "next_expected_date")
    for change in data.scenario:
        _identifier(change.kind, "scenario.kind")
        _optional_text(change.target_id)
        if change.amount_minor is not None:
            _integer(change.amount_minor, "scenario.amount_minor", nonnegative=True)
        if change.shift_days is not None and (type(change.shift_days) is not int or not 0 <= change.shift_days <= 3650):
            raise ForecastInputError("invalid_forecast_input", "shift_days должен быть целым0–3650")
        if change.factor is not None and (
            type(change.factor) not in (int, float) or not math.isfinite(change.factor) or not 0 <= change.factor <= 100
        ):
            raise ForecastInputError("invalid_forecast_input", "factor должен быть конечным0–100")
        if change.on_date is not None:
            _date(change.on_date, "scenario.on_date")
    return replace(data, txns=txns, daily_balances=balances, planned_events=sorted(events, key=lambda event: event.id))


def assess_quality(data: ForecastInput, lookback_days: int = 84) -> QualityReport:
    data = validate_input(data)
    if type(lookback_days) is not int or not 28 <= lookback_days <= 366:
        raise ForecastInputError("invalid_forecast_input", "Окно качества28–366 дней")
    observed = [txn.booked_on for txn in data.txns] + [balance.balance_date for balance in data.daily_balances]
    start = max(min(observed, default=data.as_of), data.as_of - timedelta(days=lookback_days - 1))
    net = defaultdict(int)
    for txn in data.txns:
        net[txn.booked_on] += txn.amount_minor * (1 if txn.direction == Direction.IN else -1)
    # Prefix для сверки: O(число операций + даты + остатки), без квадратичных проходов.
    days = sorted(net)
    running, cursor = 0, 0
    at_balance = {}
    for balance in data.daily_balances:
        while cursor < len(days) and days[cursor] <= balance.balance_date:
            running += net[days[cursor]]
            cursor += 1
        at_balance[balance.balance_date] = running
    breaks = []
    for previous, current in itertools.pairwise(data.daily_balances):
        total = at_balance[current.balance_date] - at_balance[previous.balance_date]
        if current.closing_balance_minor - previous.closing_balance_minor != total:
            breaks.append(current.balance_date)
    if breaks:
        start = max(start, breaks[-1] + timedelta(days=1))
    count = max(0, (data.as_of - start).days + 1) if observed else 0
    last = data.daily_balances[-1] if data.daily_balances else None
    age = (data.as_of - last.balance_date).days if last else None
    expected_opening = (
        (
            last.closing_balance_minor
            + sum(amount for day, amount in net.items() if last.balance_date < day <= data.as_of)
        )
        if last
        else None
    )
    fresh = last is not None and age <= 3 and expected_opening == data.opening_balance_minor
    observed_days = {day for day in observed if start <= day <= data.as_of}
    unobserved = max(0, count - len(observed_days))
    warnings = []
    if unobserved:
        warnings.append("Дни без наблюдаемых операций/остатков условно нулевые; полнота выгрузки не доказана.")
    if breaks:
        warnings.append("Есть несверка остатков; статистическая история начинается после последней несверки.")
    if not last:
        warnings.append("Нет подтверждённого остатка; уровень прогнозного остатка задан входным допущением.")
    elif age > 3:
        warnings.append("Начальный остаток устарел более чем на3дня; вероятность недоступна.")
    if last and expected_opening != data.opening_balance_minor:
        warnings.append(
            "Начальный остаток не согласуется с последним известным остатком и фактами; суммы не исправлялись."
        )
    if count < 28:
        warnings.append("Менее28дней пригодной истории: доступен план/точечный fallback без вероятности.")
    elif count < 56:
        warnings.append("Менее56дней пригодной истории: калиброванная вероятность недоступна.")
    simulation = count >= 28 and fresh
    probability = count >= 56 and fresh
    return QualityReport(
        "quality-v2.0",
        "empirical" if simulation else "point_only" if count else "plan_only",
        count,
        start,
        age,
        len(breaks),
        unobserved,
        simulation,
        probability,
        tuple(warnings),
    )

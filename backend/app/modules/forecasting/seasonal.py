"""Прогноз по дням недели + календарные события + парный недельный bootstrap.

Вероятности условные модельные, не банковская гарантия. Обучение только на as_of.
"""

from __future__ import annotations

import calendar
import itertools
import random
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from statistics import mean

from app.modules.categorization.service import get_categorizer, normalize
from app.modules.contracts import (
    DailyBalanceDTO,
    Direction,
    ForecastInput,
    ForecastPointDTO,
    ForecastResult,
    RecurrenceGroup,
    RecurrenceInterval,
    RiskSummary,
    TxnDTO,
)
from app.modules.forecasting.scenarios import apply_scenario
from app.modules.planning.recurrence import advance
from app.modules.planning.service import get_recurrence_detector

MODEL_VERSION = "seasonal-block-bootstrap-1.0"


def _money(value: float) -> int:
    # Все преобразования float в деньги выполняются только на границе компонента.
    return round(value)


def _quantile(values: list[int], probability: float) -> int:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return _money(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def _history(
    data: ForecastInput, lookback_days: int
) -> tuple[list[TxnDTO], list[DailyBalanceDTO], list[date], list[str], bool]:
    txns = sorted(
        (txn for txn in data.txns if txn.account_id == data.account_id and txn.booked_on <= data.as_of),
        key=lambda txn: (txn.booked_on, txn.id),
    )
    if any(txn.currency != "RUB" or txn.amount_minor < 0 for txn in txns):
        raise ValueError("Прогноз поддерживает только RUB и неотрицательные суммы")
    if len({txn.id for txn in txns}) != len(txns):
        raise ValueError("Повторный id операции в снимке")
    assignments = get_categorizer().categorize(txns)
    txns = [replace(txn, category=assignment.category.value) for txn, assignment in zip(txns, assignments, strict=True)]
    balances = sorted(
        (
            balance
            for balance in data.daily_balances
            if balance.account_id == data.account_id and balance.balance_date <= data.as_of
        ),
        key=lambda balance: balance.balance_date,
    )
    if len({balance.balance_date for balance in balances}) != len(balances):
        raise ValueError("Несколько остатков на одну дату")
    observed = [txn.booked_on for txn in txns] + [balance.balance_date for balance in balances]
    start = max(min(observed, default=data.as_of), data.as_of - timedelta(days=lookback_days - 1))
    warnings = []
    # Сверка только по уже наблюдённым остаткам. После несверки неизвестную часть
    # не восстанавливаем придуманными операциями; обучение начинаем позже неё.
    net = defaultdict(int)
    for txn in txns:
        net[txn.booked_on] += txn.amount_minor * (1 if txn.direction == Direction.IN else -1)
    for previous, current in itertools.pairwise(balances):
        total = sum(amount for day, amount in net.items() if previous.balance_date < day <= current.balance_date)
        if current.closing_balance_minor - previous.closing_balance_minor != total:
            start = max(start, current.balance_date + timedelta(days=1))
            warnings.append("Обнаружена несверка остатков; история до неё исключена из статистики.")
    days = [start + timedelta(days=offset) for offset in range(max(0, (data.as_of - start).days + 1))]
    reliable = (
        len(days) >= 28
        and bool(balances)
        and (data.as_of - balances[-1].balance_date).days <= 3
        and balances[-1].closing_balance_minor == data.opening_balance_minor
    )
    if not reliable:
        warnings.append("Вероятность недоступна: короткая история, несверка или нет свежего подтверждённого остатка.")
    return txns, balances, days, list(dict.fromkeys(warnings)), reliable


def _recurring_history_ids(groups: list[RecurrenceGroup], txns: list[TxnDTO]) -> set[str]:
    by_id = {txn.id: txn for txn in txns}
    excluded = set()
    for group in groups:
        members = [by_id[tid] for tid in group.member_transaction_ids if tid in by_id]
        if not members:
            continue
        exemplar = members[-1]
        identity = normalize(exemplar.counterparty_ref) or normalize(exemplar.counterparty_name)
        daily = defaultdict(list)
        for txn in txns:
            if (
                txn.direction == group.direction
                and txn.category == exemplar.category
                and (normalize(txn.counterparty_ref) or normalize(txn.counterparty_name)) == identity
            ):
                daily[txn.booked_on].append(txn)
        last = exemplar.booked_on
        for day, transactions in daily.items():
            amount = sum(txn.amount_minor for txn in transactions)
            if abs(amount - group.typical_amount_minor) > group.typical_amount_minor * 0.35:
                continue
            if group.interval in {RecurrenceInterval.WEEKLY, RecurrenceInterval.BIWEEKLY}:
                period = 7 if group.interval == RecurrenceInterval.WEEKLY else 14
                gap = abs((last - day).days) % period
                phase = min(gap, period - gap) <= 2
            else:
                phase = abs(day.day - last.day) <= 3 or (
                    day.day == calendar.monthrange(day.year, day.month)[1]
                    and last.day == calendar.monthrange(last.year, last.month)[1]
                )
                if group.interval == RecurrenceInterval.QUARTERLY:
                    phase = phase and (last.month - day.month) % 3 == 0
            if phase:
                excluded.update(txn.id for txn in transactions)
    return excluded


def _schedule(data: ForecastInput, groups: list[RecurrenceGroup]):
    state = apply_scenario(data, groups)
    end = data.as_of + timedelta(days=data.horizon_days)
    schedule = []
    occurrences = []
    by_id = {txn.id: txn for txn in data.txns}
    identities_by_group = {}
    for group in groups:
        members = [by_id[member_id] for member_id in group.member_transaction_ids if member_id in by_id]
        identities = {normalize(group.counterparty_ref)} - {""}
        for member in members:
            identities.update({normalize(member.counterparty_ref), normalize(member.counterparty_name)} - {""})
        identities_by_group[group.group_id] = identities
        day = group.next_expected_date
        if day is None:
            continue
        # Якорь выводится из наблюдений, иначе Apr30 -> May30 сломает конец месяца.
        member_days = [member.booked_on for member in members]
        anchor = max((day.day for day in member_days), default=day.day)
        if member_days and all(d.day == calendar.monthrange(d.year, d.month)[1] for d in member_days):
            anchor = 31
        while day <= end:
            if day > data.as_of:
                occurrences.append([day, group, False])
            try:
                day = advance(day, group.interval, anchor)
            except (ValueError, OverflowError):
                # Следующая occurrence вне представимого календаря, значит и вне end.
                break
    replaced = set()
    # Матчинг с исходной датой события производится до сценарного переноса:
    # delay_event не должен возвращать исходное регулярное обязательство второй раз.
    originals = {event.id: event for event in data.planned_events if event.available_at <= data.as_of}
    for event in sorted(state.events, key=lambda event: event.id):
        original = originals[event.id]
        candidates = []
        for index, (day, group, _used) in enumerate(occurrences):
            if index in replaced or event.direction != group.direction:
                continue
            explicit = event.recurrence_group == group.group_id
            identity = bool(
                event.counterparty_ref and normalize(event.counterparty_ref) in identities_by_group[group.group_id]
            )
            if (explicit or identity) and abs((original.due_date - day).days) <= 3:
                candidates.append(index)
        # Не угадываем, если один счёт подходит нескольким регулярностям.
        if len(candidates) == 1:
            replaced.add(candidates[0])
        if event.status not in {"planned", "partially_paid"} or event.remaining_amount_minor <= 0:
            continue
        due = max(event.due_date, data.as_of + timedelta(days=1))
        if due <= end:
            schedule.append((due, event.direction, event.remaining_amount_minor, "planned", event.id))
    for index, (day, group, _) in enumerate(occurrences):
        if index not in replaced:
            amount = _money(group.typical_amount_minor * state.recurring_factors[group.group_id])
            schedule.append((day, group.direction, amount, "recurrence", group.group_id))
    for day, amount in sorted(state.extra_expenses.items()):
        schedule.append((day, Direction.OUT, amount, "scenario_expense", None))
    return state, schedule


class SeasonalForecastService:
    def __init__(self, paths: int = 200, lookback_days: int = 84):
        if not 20 <= paths <= 2000:
            raise ValueError("Число траекторий должно быть20–2000")
        self.paths = paths
        if lookback_days not in {28, 56, 84}:
            raise ValueError("Окно истории должно быть28,56 или84 дня")
        self.lookback_days = lookback_days

    @property
    def model_version(self) -> str:
        """Публичная версия для фиксации модели в очереди и сценарном снимке."""
        return f"{MODEL_VERSION}-w{self.lookback_days}"

    def run(self, data: ForecastInput) -> ForecastResult:
        if not 1 <= data.horizon_days <= 366:
            raise ValueError("Горизонт должен быть1–366 дней")
        txns, _balances, days, warnings, reliable = _history(data, self.lookback_days)
        # Повторный расчёт по причинному снимку не доверяет внешним агрегатам,
        # чьё происхождение и дата обучения не представлены в DTO.
        groups = get_recurrence_detector().detect(txns, data.as_of)
        clean = replace(data, txns=txns)
        state, schedule = _schedule(clean, groups)
        excluded = _recurring_history_ids(groups, txns)
        residual = defaultdict(lambda: [0, 0])
        for txn in txns:
            if txn.id not in excluded:
                residual[txn.booked_on][0 if txn.direction == Direction.IN else 1] += txn.amount_minor
        weekday = {}
        for weekday_index in range(7):
            samples = [residual[day] for day in days if day.weekday() == weekday_index]
            weekday[weekday_index] = [mean(pair[index] for pair in samples) if samples else 0 for index in range(2)]
        fixed = defaultdict(lambda: [0, 0])
        for day, direction, amount, _kind, _ref in schedule:
            fixed[day][0 if direction == Direction.IN else 1] += amount
        future = [data.as_of + timedelta(days=offset) for offset in range(1, data.horizon_days + 1)]
        rng = random.Random(data.seed)  # noqa: S311 -- воспроизводимая симуляция, не криптография
        trajectories = [[] for _ in future]
        negative_any = 0
        if reliable:
            starts = {
                weekday_index: [
                    index for index, day in enumerate(days) if day.weekday() == weekday_index and index + 6 < len(days)
                ]
                for weekday_index in range(7)
            }
            for _path in range(self.paths):
                balance = data.opening_balance_minor
                any_negative = False
                block_start = 0
                for index, day in enumerate(future):
                    if index % 7 == 0:
                        block_start = rng.choice(starts[day.weekday()])
                    incoming, outgoing = residual[days[block_start + index % 7]]
                    balance += _money(incoming * state.inflow_factor) - outgoing + fixed[day][0] - fixed[day][1]
                    trajectories[index].append(balance)
                    any_negative |= balance < 0
                negative_any += any_negative
        points = []
        balance = data.opening_balance_minor
        for index, day in enumerate(future):
            incoming = _money(weekday[day.weekday()][0] * state.inflow_factor) + fixed[day][0]
            outgoing = _money(weekday[day.weekday()][1]) + fixed[day][1]
            balance += incoming - outgoing
            values = trajectories[index] if reliable else [balance]
            points.append(
                ForecastPointDTO(
                    day,
                    incoming,
                    outgoing,
                    _quantile(values, 0.1),
                    _quantile(values, 0.5),
                    _quantile(values, 0.9),
                    sum(value < 0 for value in values) / self.paths if reliable else None,
                )
            )
        negative = [point for point in points if point.balance_p50_minor < 0]
        risk = RiskSummary(
            reliable,
            negative[0].point_date if negative else None,
            max(-point.balance_p50_minor for point in negative) if negative else None,
            negative_any / self.paths if reliable else None,
            sorted(
                {
                    ref
                    for day, direction, _, kind, ref in schedule
                    if direction == Direction.OUT and kind == "planned" and ref and day <= negative[0].point_date
                }
            )
            if negative
            else [],
        )
        explanations = list(state.explanations)
        for _day, direction, amount, kind, ref in schedule:
            explanations.append(
                {
                    "kind": kind,
                    "label": "Ожидаемое поступление" if direction == Direction.IN else "Ожидаемое списание",
                    "amount_minor": amount,
                    "source_ref": ref,
                    "detail": {"date": _day.isoformat(), "direction": direction.value},
                }
            )
        explanations.append(
            {
                "kind": "residual",
                "label": "Нерегулярный поток по дням недели",
                "detail": {"history_days": len(days), "excluded_recurring_operations": len(excluded)},
            }
        )
        return ForecastResult(
            self.model_version,
            points,
            risk,
            [
                "Потоки одного наблюдаемого счёта RUB; переводы собственных средств влияют на остаток.",
                f"Средние по дням недели за последние{self.lookback_days} дня; регулярности вынесены отдельно.",
                "Парный bootstrap недель сохраняет связь притока и оттока; вероятности модельные и не калиброваны.",
                "Дни без операций считаются нулевыми только при допущении полноты выгрузки; несверки отмечены.",
                "p10/p50/p90 — квантили траекторий; inflow/outflow — ожидаемые потоки, не дельта p50.",
            ],
            warnings,
            {
                "method": "seasonal_block_bootstrap",
                "summary": "Модельный прогноз остатка и его компонентов.",
                "explanations": explanations,
                "paths": self.paths if reliable else 0,
                "history_days": len(days),
                "recurrence_count": len(groups),
                "recurrence_ids": [group.group_id for group in groups],
                "daily_components": [
                    {"date": day.isoformat(), "planned_in_minor": fixed[day][0], "planned_out_minor": fixed[day][1]}
                    for day in future
                ],
            },
        )

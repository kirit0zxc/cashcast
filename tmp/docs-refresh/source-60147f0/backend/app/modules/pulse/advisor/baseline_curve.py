# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Базовая кривая остатка для плана спасения: остаток на начало + поштучные будущие потоки.

Кривая простая и честно подписана как оценка. Её задача — дать планировщику список потоков
с гибкостью, а не соревноваться с моделью прогноза основного проекта. При интеграции
средние потоки заменяются прогнозом бэкенда, а поштучные (календарь, деньги владельца)
остаются: планировщику неважно, чья кривая, он работает со сдвигами потоков.

Состав:
- регулярные обязательства — календарь 2б, поштучно (hard/regular);
- поставщики — средний поток за 8 недель с профилем по дню недели (flexible);
- прочие жёсткие/регулярные вне календаря — тот же средний поток (не двигаем);
- деньги владельца и переводы на свой счёт — «если выведете как обычно» (owner/internal);
- поступления — средний операционный поток за 8 недель по дню недели.
Займы учредителя, пополнения собственными средствами и кредиты в базу не входят:
это ручное спасение, которое план должен заменить, а не спрятать.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .dataset import Operation
from .documents import parse_purpose
from .outflows import classify_outflow
from .payment_calendar import (
    CalendarConfig,
    adjust_to_business_day,
    detect_series,
    expected_payments,
    series_key,
)


@dataclass(frozen=True, slots=True)
class CurveConfig:
    horizon_days: int = 45  # считаем 45, показываем 30: перенос не должен прятать яму за край
    flow_window_days: int = 56  # 8 недель для средних потоков
    owner_window_days: int = 182  # привычки владельца — за полгода
    owner_min_months: int = 2  # реже — не привычка, в базу не ставим
    # Привычки владельца в кривой — как ожидаемое значение: это улучшает предупреждение.
    # Но планировщик по умолчанию их вычитает: backtest показал, что в кризис владелец
    # в 85% случаев и так ничего не выводит, и «отложить вывод» был бы фантомным рычагом.
    include_owner_habits: bool = True


@dataclass(frozen=True, slots=True)
class Flow:
    ref: str  # уникальный id: по нему планировщик сдвигает поток
    day: date
    amount_minor: int  # > 0 поступление, < 0 списание
    kind: str
    flexibility: str  # hard | regular | flexible | owner | internal | inflow
    label: str
    source: str  # calendar | flow_average | owner_habit


@dataclass(slots=True)
class BaseCurve:
    company_id: str
    as_of: date
    opening_balance_minor: int
    horizon_days: int
    flows: list[Flow] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def days(self) -> list[date]:
        return [self.as_of + timedelta(days=i) for i in range(1, self.horizon_days + 1)]

    def balances(self, flows: Sequence[Flow] | None = None) -> list[int]:
        """Остаток на конец каждого дня горизонта для заданного набора потоков."""
        per_day: dict[date, int] = defaultdict(int)
        for f in self.flows if flows is None else flows:
            per_day[f.day] += f.amount_minor
        out, bal = [], self.opening_balance_minor
        for d in self.days:
            bal += per_day.get(d, 0)
            out.append(bal)
        return out


def _business_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _weekday_profile(ops: Sequence[Operation], start: date, end: date) -> dict[int, float]:
    """Средняя сумма за рабочий день каждого дня недели в окне (start, end]."""
    window_days = _business_days(start + timedelta(days=1), end)
    count = defaultdict(int)
    for d in window_days:
        count[d.weekday()] += 1
    total: dict[int, int] = defaultdict(int)
    for op in ops:
        total[op.op_date.weekday()] += op.amount_minor
    return {wd: total[wd] / count[wd] for wd in count if count[wd]}


def opening_balance(operations: Sequence[Operation], as_of: date) -> int | None:
    last = None
    for op in operations:
        if op.op_date <= as_of and op.balance_eod_minor is not None:
            last = op
    return last.balance_eod_minor if last else None


def owner_habits(operations: Sequence[Operation], as_of: date, cfg: CurveConfig | None = None) -> dict[str, int]:
    """Средний вывод в месяц по привычкам владельца: {'owner'|'internal': копейки/мес}."""
    cfg = cfg or CurveConfig()
    start = as_of - timedelta(days=cfg.owner_window_days)
    total: dict[str, int] = defaultdict(int)
    months: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for op in operations:
        if op.direction == "out" and start < op.op_date <= as_of:
            flex = classify_outflow(op).flexibility
            if flex in ("owner", "internal"):
                total[flex] += op.amount_minor
                months[flex].add((op.op_date.year, op.op_date.month))
    return {
        flex: amount * 30 // cfg.owner_window_days
        for flex, amount in total.items()
        if len(months[flex]) >= cfg.owner_min_months
    }


def build_base_curve(
    operations: Sequence[Operation],
    company_id: str,
    as_of: date,
    cfg: CurveConfig | None = None,
    calendar_cfg: CalendarConfig | None = None,
) -> BaseCurve:
    cfg = cfg or CurveConfig()
    history = [op for op in operations if op.op_date <= as_of]
    opening = opening_balance(history, as_of)
    curve = BaseCurve(
        company_id=company_id, as_of=as_of, opening_balance_minor=opening or 0, horizon_days=cfg.horizon_days
    )
    if opening is None:
        curve.warnings.append("Нет остатка на дату среза — кривую не построить.")
        return curve
    end = as_of + timedelta(days=cfg.horizon_days)
    future_days = _business_days(as_of + timedelta(days=1), end)
    flow_start = as_of - timedelta(days=cfg.flow_window_days)
    if not history or history[0].op_date > flow_start:
        curve.warnings.append("История короче 8 недель — средние потоки ненадёжны.")

    # 1. Календарь регулярных обязательств — поштучно.
    series = detect_series(history, as_of, calendar_cfg)
    series_keys = {s.key for s in series}
    for i, p in enumerate(expected_payments(series, as_of, cfg.horizon_days, calendar_cfg)):
        curve.flows.append(Flow(f"cal:{i}", p.due_date, -p.amount_minor, p.kind, p.flexibility, p.label, "calendar"))

    # 2–3. Средние потоки за 8 недель.
    recent = [op for op in history if op.op_date > flow_start]
    suppliers, other_fixed, inflows = [], [], []
    for op in recent:
        if op.direction == "in":
            if parse_purpose(op.purpose).non_operating is None:
                inflows.append(op)
            continue
        cls = classify_outflow(op)
        if cls.kind == "purchases":
            suppliers.append(op)
        elif cls.flexibility in ("hard", "regular") and cls.kind != "enforcement":
            sk = series_key(op)
            if sk is None or sk[0] not in series_keys:
                other_fixed.append(op)  # регулярный по смыслу, но без ритма — средним потоком
    for name, ops, sign, kind, flex, label in (
        ("in", inflows, 1, "revenue", "inflow", "Поступления (средний поток)"),
        ("sup", suppliers, -1, "purchases", "flexible", "Поставщики (обычный поток)"),
        ("fix", other_fixed, -1, "other_fixed", "regular", "Прочие обязательные расходы"),
    ):
        profile = _weekday_profile(ops, flow_start, as_of)
        for d in future_days:
            amount = round(profile.get(d.weekday(), 0.0))
            if amount:
                curve.flows.append(Flow(f"{name}:{d.isoformat()}", d, sign * amount, kind, flex, label, "flow_average"))

    # 4. Привычки владельца: вывод денег и переводы на свой счёт в другом банке.
    owner_start = as_of - timedelta(days=cfg.owner_window_days)
    habits: dict[str, list[Operation]] = defaultdict(list)
    for op in history:
        if op.direction == "out" and op.op_date > owner_start:
            cls = classify_outflow(op)
            if cls.flexibility in ("owner", "internal"):
                habits[cls.flexibility].append(op)
    for flex, ops in habits.items() if cfg.include_owner_habits else ():
        months = {(op.op_date.year, op.op_date.month) for op in ops}
        if len(months) < cfg.owner_min_months:
            continue
        monthly = sum(op.amount_minor for op in ops) * 30 // cfg.owner_window_days
        day = int(statistics.median(op.op_date.day for op in ops))
        label = (
            "Вывод денег владельцем (как обычно)"
            if flex == "owner"
            else "Перевод на свой счёт в другом банке (как обычно)"
        )
        kind = "owner_withdrawal" if flex == "owner" else "internal_transfer"
        for offset in range(0, cfg.horizon_days // 28 + 2):
            total = as_of.year * 12 + as_of.month - 1 + offset
            y, m = total // 12, total % 12 + 1
            try:
                due = date(y, m, day)
            except ValueError:
                due = date(y, m, 28)
            due = adjust_to_business_day(due, backwards=False)
            if as_of < due <= end:
                curve.flows.append(Flow(f"{flex}:{due.isoformat()}", due, -monthly, kind, flex, label, "owner_habit"))

    curve.flows.sort(key=lambda f: (f.day, f.ref))
    curve.assumptions += [
        "Остаток на начало — по выписке на дату среза.",
        "Поступления и оплаты поставщикам — средний поток за 8 недель по дням недели; сезонность не учтена.",
        "Регулярные обязательства — календарь платежей по истории.",
        "Вывод денег владельцем — «как обычно» за последние полгода (для предупреждения).",
        "Займы учредителя, пополнения собственными средствами и новые кредиты не учтены.",
    ]
    return curve

# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Календарь ожидаемых регулярных списаний: что, когда и на какую сумму придётся платить.

Это вход для плана спасения: ему нужен не только итог по дню, но и поштучный список платежей
с гибкостью (что можно двигать, а что нет). Регулярные платежи ищем по истории до as_of:
- серия = вид платежа + получатель (зарплату и ЕНП собираем без получателя: это одна
  обязанность, разбитая на много переводов);
- monthly — платится почти каждый месяц в похожий день; weekly — раз в неделю (топливо);
- остальное нерегулярно и в календарь не попадает (реклама, деньги владельца, разовые).

Перенос с выходных измерен по датасету: зарплату платят раньше (в пятницу), ЕНП и прочее —
в следующий рабочий день. Праздники РФ не учтены — это известный источник ошибки дат.
Временный дубль регулярностей агента B основного проекта; при интеграции заменяется адаптером.
"""

from __future__ import annotations

import calendar as _cal
import itertools
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Literal

from .dataset import Operation
from .outflows import classify_outflow

METHOD_VERSION = "payment-calendar-0.1"

Cadence = Literal["monthly", "weekly"]

KIND_LABELS = {
    "tax": "Единый налоговый платёж",
    "payroll:advance": "Зарплата — аванс",
    "payroll:final": "Зарплата — окончательный расчёт",
    "payroll:other": "Выплаты по ГПХ",
    "loan": "Кредит / лизинг",
    "rent": "Аренда",
    "utilities": "Коммунальные услуги и связь",
    "fees": "Комиссии банка",
    "services": "Услуги",
    "marketing": "Реклама",
    "fuel_transport": "Топливо и дороги",
}


@dataclass(frozen=True, slots=True)
class CalendarConfig:
    lookback_days: int = 183  # полгода истории для поиска ритма
    min_active_months: int = 4  # из ~6: «почти каждый месяц»
    max_silence_days: int = 45  # дольше молчит — серия, видимо, закончилась
    amount_months: int = 3  # сумма — медиана последних 3 месяцев
    weekly_min_per_month: float = 3.0
    business_day_shift: bool = True  # выключается в backtest для сравнения
    # Сумма ЕНП: seasonal_confirmed — как в том же месяце прошлого квартала, если это
    # подтверждает и позапрошлый квартал; иначе медиана. Выбор — по validation, см. reports/.
    tax_amount: Literal["seasonal_confirmed", "seasonal_quarter", "median"] = "seasonal_confirmed"
    tax_lookback_days: int = 400  # для квартальной сезонности ЕНП нужно больше года
    seasonal_max_ratio: float = 1.5


@dataclass(frozen=True, slots=True)
class RecurringSeries:
    key: str
    kind: str
    flexibility: str
    cadence: Cadence
    label: str
    counterparty_name: str | None
    typical_day: int | None  # день месяца для monthly
    amount_minor: int  # типичная сумма за период (месяц или неделю)
    last_payment_date: date
    active_months: int
    monthly_totals_minor: dict[str, int]  # 'YYYY-MM' -> сумма, для сезонности и отладки


@dataclass(frozen=True, slots=True)
class ExpectedPayment:
    due_date: date
    amount_minor: int
    series_key: str
    kind: str
    flexibility: str
    cadence: Cadence
    label: str
    basis: str  # откуда взялась сумма — показываем пользователю


@dataclass(slots=True)
class CalendarReport:
    company_id: str
    as_of: date
    horizon_days: int
    method_version: str
    payments: list[ExpectedPayment] = field(default_factory=list)
    series: list[RecurringSeries] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


_ADVANCE = re.compile(r"аванс", re.IGNORECASE)
_FINAL = re.compile(r"окончательн|заработная\s+плата\s+за", re.IGNORECASE)


def series_key(op: Operation) -> tuple[str, str, str] | None:
    """(ключ серии, kind, гибкость) для жёстких и регулярных списаний; иначе None."""
    cls = classify_outflow(op)
    if cls.flexibility not in ("hard", "regular") or cls.kind == "enforcement":
        return None
    if cls.kind == "payroll":
        purpose = op.purpose or ""
        sub = "advance" if _ADVANCE.search(purpose) else "final" if _FINAL.search(purpose) else "other"
        return f"payroll:{sub}", cls.kind, cls.flexibility
    if cls.kind == "tax":
        return "tax", cls.kind, cls.flexibility
    who = op.counterparty_inn or (op.counterparty_name or "").strip().lower() or "?"
    return f"{cls.kind}:{who}", cls.kind, cls.flexibility


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_months(d: date, months: int) -> tuple[int, int]:
    total = d.year * 12 + d.month - 1 + months
    return total // 12, total % 12 + 1


def adjust_to_business_day(d: date, backwards: bool) -> date:
    step = -1 if backwards else 1
    while d.weekday() >= 5:
        d += timedelta(days=step)
    return d


def detect_series(
    operations: Iterable[Operation], as_of: date, cfg: CalendarConfig | None = None
) -> list[RecurringSeries]:
    cfg = cfg or CalendarConfig()
    start = as_of - timedelta(days=cfg.lookback_days)
    tax_start = as_of - timedelta(days=max(cfg.lookback_days, cfg.tax_lookback_days))
    groups: dict[str, list[Operation]] = defaultdict(list)
    meta: dict[str, tuple[str, str]] = {}
    for op in operations:
        if op.direction != "out" or not (tax_start < op.op_date <= as_of):
            continue
        sk = series_key(op)
        if sk is None:
            continue
        key, kind, flex = sk
        if key != "tax" and op.op_date <= start:
            continue
        groups[key].append(op)
        meta[key] = (kind, flex)

    result: list[RecurringSeries] = []
    for key, ops in groups.items():
        ops.sort(key=lambda o: o.op_date)
        last = ops[-1].op_date
        if (as_of - last).days > cfg.max_silence_days:
            continue
        totals: dict[str, int] = defaultdict(int)
        counts: dict[str, int] = defaultdict(int)
        first_day: dict[str, int] = {}
        for op in ops:
            mk = _month_key(op.op_date)
            totals[mk] += op.amount_minor
            counts[mk] += 1
            first_day.setdefault(mk, op.op_date.day)
        recent_months = sum(1 for m in totals if m > _month_key(start))
        if recent_months < cfg.min_active_months:
            continue
        kind, flex = meta[key]
        per_month = statistics.median(counts.values())
        dates = sorted({op.op_date for op in ops})
        gaps = [(b - a).days for a, b in itertools.pairwise(dates)]
        if per_month >= cfg.weekly_min_per_month and gaps and 5 <= statistics.median(gaps) <= 9:
            cadence: Cadence = "weekly"
            amount = int(statistics.median([op.amount_minor for op in ops[-8:]]))
            typical_day = None
        elif per_month <= 2:
            cadence = "monthly"
            recent = [totals[m] for m in sorted(totals)[-cfg.amount_months :]]
            # День берём только из последних полугода: старые месяцы ЕНП нужны лишь для сумм.
            first_day = {m: d for m, d in first_day.items() if m > _month_key(start)}
            amount = int(statistics.median(recent))
            # День первой оплаты месяца: второй перевод (доплата ЕНП 30-го) не сдвигает ритм.
            typical_day = int(statistics.median(first_day.values()))
        else:
            continue  # несколько платежей в месяц без недельного ритма — нерегулярно
        label_key = key if key.startswith("payroll:") else kind
        result.append(
            RecurringSeries(
                key=key,
                kind=kind,
                flexibility=flex,
                cadence=cadence,
                label=KIND_LABELS.get(label_key, kind),
                counterparty_name=None if kind in ("tax", "payroll") else ops[-1].counterparty_name,
                typical_day=typical_day,
                amount_minor=amount,
                last_payment_date=last,
                active_months=recent_months,
                monthly_totals_minor=dict(sorted(totals.items())),
            )
        )
    result.sort(key=lambda s: -s.amount_minor)
    return result


def _monthly_amount(series: RecurringSeries, year: int, month: int, cfg: CalendarConfig) -> tuple[int, str]:
    if series.kind == "tax" and cfg.tax_amount != "median":
        # ЕНП зависит от места месяца в квартале (авансы УСН/НДС). Но разовый всплеск
        # (годовой налог, доначисление) копировать нельзя: при seasonal_confirmed требуем,
        # чтобы позапрошлый квартал подтверждал уровень прошлого.
        y3, m3 = _shift_months(date(year, month, 1), -3)
        y6, m6 = _shift_months(date(year, month, 1), -6)
        q1 = series.monthly_totals_minor.get(f"{y3:04d}-{m3:02d}")
        q2 = series.monthly_totals_minor.get(f"{y6:04d}-{m6:02d}")
        if q1 is not None and cfg.tax_amount == "seasonal_quarter":
            return q1, f"как за {m3:02d}.{y3} (тот же месяц квартала)"
        if q1 and q2 and max(q1, q2) <= cfg.seasonal_max_ratio * min(q1, q2):
            return q1, (f"как за {m3:02d}.{y3}, подтверждено {m6:02d}.{y6} (тот же месяц квартала)")
    return series.amount_minor, "медиана последних 3 месяцев"


def expected_payments(
    series: Sequence[RecurringSeries],
    as_of: date,
    horizon_days: int = 30,
    cfg: CalendarConfig | None = None,
) -> list[ExpectedPayment]:
    cfg = cfg or CalendarConfig()
    end = as_of + timedelta(days=horizon_days)
    out: list[ExpectedPayment] = []
    for s in series:
        if s.cadence == "weekly":
            due = s.last_payment_date + timedelta(days=7)
            while due <= end:
                d = adjust_to_business_day(due, backwards=False) if cfg.business_day_shift else due
                if as_of < d <= end:
                    out.append(
                        ExpectedPayment(
                            d,
                            s.amount_minor,
                            s.key,
                            s.kind,
                            s.flexibility,
                            s.cadence,
                            s.label,
                            "медиана последних 8 оплат",
                        )
                    )
                due += timedelta(days=7)
            continue
        paid_this_month = _month_key(s.last_payment_date) == _month_key(as_of)
        for offset in range(0, horizon_days // 28 + 2):
            year, month = _shift_months(as_of, offset)
            if offset == 0 and paid_this_month:
                continue
            day = min(s.typical_day or 1, _cal.monthrange(year, month)[1])
            due = date(year, month, day)
            if cfg.business_day_shift:
                due = adjust_to_business_day(due, backwards=s.kind == "payroll")
            if as_of < due <= end:
                amount, basis = _monthly_amount(s, year, month, cfg)
                out.append(ExpectedPayment(due, amount, s.key, s.kind, s.flexibility, s.cadence, s.label, basis))
    out.sort(key=lambda p: (p.due_date, -p.amount_minor))
    return out


def build_calendar(
    operations: Sequence[Operation],
    company_id: str,
    as_of: date,
    horizon_days: int = 30,
    cfg: CalendarConfig | None = None,
) -> CalendarReport:
    cfg = cfg or CalendarConfig()
    history = [op for op in operations if op.op_date <= as_of]
    report = CalendarReport(
        company_id=company_id, as_of=as_of, horizon_days=horizon_days, method_version=METHOD_VERSION
    )
    if not history:
        report.warnings.append("Нет операций до даты среза — календарь не построить.")
        return report
    if (as_of - history[0].op_date).days < cfg.lookback_days:
        report.warnings.append("История короче полугода — часть регулярных платежей может быть не найдена.")
    report.series = detect_series(history, as_of, cfg)
    report.payments = expected_payments(report.series, as_of, horizon_days, cfg)
    by_flex: dict[str, int] = defaultdict(int)
    for p in report.payments:
        by_flex[p.flexibility] += p.amount_minor
    report.summary = {
        "series": len(report.series),
        "payments": len(report.payments),
        "total_minor": sum(p.amount_minor for p in report.payments),
        "by_flexibility_minor": dict(by_flex),
    }
    report.warnings.append("Праздничные дни РФ не учтены: дата может сдвинуться на 1–3 дня.")
    return report

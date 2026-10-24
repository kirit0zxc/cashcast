# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Стресс-тест по реальным клиентам: «что будет, если конкретный клиент заплатит позже или уйдёт».

Персональная версия сценария кейса «крупный клиент заплатит на 2–4 недели позже». Вместо
догадки пользователя берём поведение клиента из истории (рейтинг):
- задержка — насколько позже обычного клиент уже платил (p90 − медиана задержки от
  документа), но не меньше 14 и не больше 28 дней — коридор кейса;
- уход — для клиентов с оценкой D или ранним сигналом, и для крупнейшего клиента.

Клиенты — только B2B-контрагенты из рейтинга (оплаты по документам). Эквайринг, СБП и
маркетплейсы — каналы продаж, а не клиенты: для них в основном проекте есть сценарий
«снижение выручки».

Доля клиента в поступлениях — его доля в операционной выручке за те же 8 недель, из которых
базовая кривая строит средний поток. Сценарий берёт эту долю из каждого дня потока и
сдвигает (задержка) или убирает (уход). Так стресс согласован с кривой и работает с любой
кривой, где поступления — отдельные потоки.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

from .baseline_curve import BaseCurve, Flow
from .counterparties import (
    RatingConfig,
    RatingReport,
    payment_lag_days,
    rate_counterparties,
    split_incoming,
)
from .dataset import Operation

METHOD_VERSION = "client-stress-0.1"


@dataclass(frozen=True, slots=True)
class StressConfig:
    window_days: int = 56  # то же окно, что у среднего потока базовой кривой
    min_share: float = 0.05  # клиенты меньше 5% поступлений на кривую почти не влияют
    top_n: int = 5
    delay_min_days: int = 14  # коридор кейса «на 2–4 недели позже»
    delay_max_days: int = 28


@dataclass(frozen=True, slots=True)
class ClientScenario:
    counterparty_key: str
    counterparty_name: str | None
    counterparty_inn: str | None
    grade: str | None
    kind: Literal["delay", "loss"]
    delay_days: int | None
    share_of_inflows: float
    title: str
    basis: str
    min_balance_minor: int
    # Насколько меньше денег на счёте в худший день горизонта, чем в базе. Падение
    # минимума недооценивает дыру: минимум базы часто в первые дни, до эффекта задержки.
    worst_day_shortfall_minor: int
    worst_day: date
    first_gap_date: date | None
    max_deficit_minor: int
    creates_gap: bool  # в базе минуса нет, в сценарии есть


@dataclass(slots=True)
class StressReport:
    company_id: str
    as_of: date
    method_version: str
    applicable: bool
    base_min_balance_minor: int
    base_first_gap_date: date | None
    scenarios: list[ClientScenario] = field(default_factory=list)
    most_dangerous: str | None = None  # counterparty_key сценария с наибольшим падением
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


def _rub(minor: int) -> str:
    return f"{minor / 100:,.0f} ₽".replace(",", " ")


def _stats(curve: BaseCurve, flows: Sequence[Flow]) -> tuple[int, date | None]:
    bal = curve.balances(flows)
    first_gap = next((d for d, b in zip(curve.days, bal, strict=True) if b < 0), None)
    return min(bal), first_gap


def _worst_shortfall(curve: BaseCurve, base: Sequence[Flow], stressed: Sequence[Flow]) -> tuple[int, date]:
    diffs = [b - s for b, s in zip(curve.balances(base), curve.balances(stressed), strict=True)]
    i = max(range(len(diffs)), key=diffs.__getitem__)
    return diffs[i], curve.days[i]


def client_shares(operations: Sequence[Operation], as_of: date, window_days: int) -> dict[str, float]:
    """Доля каждого клиента в операционных поступлениях за окно (as_of − window, as_of]."""
    start = as_of - timedelta(days=window_days)
    recent = [op for op in operations if start < op.op_date <= as_of]
    by_client, operating, _ = split_incoming(recent)
    total = sum(op.amount_minor for op in operating)
    if not total:
        return {}
    return {key: sum(p.op.amount_minor for p in pays) / total for key, pays in by_client.items()}


def _apply(flows: Sequence[Flow], share: float, kind: str, delay_days: int, horizon_end: date) -> list[Flow]:
    """Отделяет долю клиента от каждого дня поступлений и сдвигает или убирает её."""
    out: list[Flow] = []
    for f in flows:
        if f.flexibility != "inflow" or f.amount_minor <= 0:
            out.append(f)
            continue
        part = round(f.amount_minor * share)
        out.append(replace(f, amount_minor=f.amount_minor - part))
        if kind == "delay" and part:
            new_day = f.day + timedelta(days=delay_days)
            if new_day <= horizon_end:
                out.append(replace(f, ref=f"{f.ref}:delayed", day=new_day, amount_minor=part))
    return out


def _delay_days(lags: list[int], cfg: StressConfig) -> tuple[int, str]:
    if len(lags) >= 5:
        ordered = sorted(lags)
        p90 = ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]
        extra = p90 - statistics.median(ordered)
        if extra >= cfg.delay_min_days:
            days = int(min(extra, cfg.delay_max_days))
            return days, (
                f"так бывало в 10% его оплат: обычно {statistics.median(ordered):g} дн. "
                f"после документа, в худших случаях {p90} дн."
            )
    return cfg.delay_min_days, "сценарий кейса: задержка на 2 недели"


def stress_clients(
    curve: BaseCurve,
    operations: Sequence[Operation],
    cfg: StressConfig | None = None,
    rating: RatingReport | None = None,
) -> StressReport:
    cfg = cfg or StressConfig()
    as_of = curve.as_of
    history = [op for op in operations if op.op_date <= as_of]
    # Как и план спасения, считаем без «вывода денег владельцем как обычно».
    flows = [f for f in curve.flows if f.source != "owner_habit"]
    base_min, base_gap = _stats(curve, flows)
    report = StressReport(
        company_id=curve.company_id,
        as_of=as_of,
        method_version=METHOD_VERSION,
        applicable=False,
        base_min_balance_minor=base_min,
        base_first_gap_date=base_gap,
    )
    if not curve.flows:
        report.warnings.append("Нет кривой остатка — стресс-тест не построить.")
        return report

    rating = rating or rate_counterparties(history, curve.company_id, as_of)
    rated = {c.counterparty_key: c for c in rating.clients}
    shares = client_shares(history, as_of, cfg.window_days)
    by_client, _, _ = split_incoming(history)
    candidates = sorted(
        ((k, s) for k, s in shares.items() if s >= cfg.min_share and k in rated), key=lambda kv: -kv[1]
    )[: cfg.top_n]
    if not candidates:
        report.warnings.append(
            "Нет B2B-клиентов с долей поступлений от 5%: деньги идут "
            "через эквайринг, СБП или от многих мелких покупателей. "
            "Используйте сценарий снижения выручки."
        )
        return report

    horizon_end = curve.days[-1]
    largest = candidates[0][0]
    for key, share in candidates:
        payments = by_client[key]
        last = payments[-1].op
        info = rated.get(key)
        lags = [lag for p in payments if (lag := payment_lag_days(p, RatingConfig())) is not None]
        kinds: list[str] = ["delay"]
        if key == largest or (info and (info.grade == "D" or info.early_warning)):
            kinds.append("loss")
        for kind in kinds:
            days, basis = _delay_days(lags, cfg) if kind == "delay" else (0, "")
            if kind == "loss":
                basis = "крупнейший клиент" if key == largest else "оценка D или ранний сигнал ухода"
            stressed = _apply(flows, share, kind, days, horizon_end)
            s_min, s_gap = _stats(curve, stressed)
            shortfall, worst_day = _worst_shortfall(curve, flows, stressed)
            name = last.counterparty_name or "клиент"
            title = (
                f"Если {name} заплатит на {days} дн. позже обычного"
                if kind == "delay"
                else f"Если {name} перестанет платить"
            )
            report.scenarios.append(
                ClientScenario(
                    counterparty_key=key,
                    counterparty_name=last.counterparty_name,
                    counterparty_inn=last.counterparty_inn,
                    grade=info.grade if info else None,
                    kind=kind,  # type: ignore[arg-type]
                    delay_days=days if kind == "delay" else None,
                    share_of_inflows=round(share, 3),
                    title=title,
                    basis=basis,
                    min_balance_minor=s_min,
                    worst_day_shortfall_minor=shortfall,
                    worst_day=worst_day,
                    first_gap_date=s_gap,
                    max_deficit_minor=max(0, -s_min),
                    creates_gap=base_gap is None and s_gap is not None,
                )
            )
    # Сначала сценарии с разрывом (раньше — опаснее), затем по размеру дыры.
    report.scenarios.sort(
        key=lambda s: (s.first_gap_date is None, s.first_gap_date or horizon_end, -s.worst_day_shortfall_minor)
    )
    report.applicable = True
    worst = report.scenarios[0]
    report.most_dangerous = worst.counterparty_key if worst.worst_day_shortfall_minor > 0 else None
    return report


def describe(s: ClientScenario) -> str:
    """Одна фраза для интерфейса."""
    if s.first_gap_date is None:
        return (
            f"{s.title} — к {s.worst_day:%d.%m} на счёте будет на "
            f"{_rub(s.worst_day_shortfall_minor)} меньше, но разрыва не будет."
        )
    return f"{s.title} — разрыв {s.first_gap_date:%d.%m}, не хватит до {_rub(s.max_deficit_minor)}."

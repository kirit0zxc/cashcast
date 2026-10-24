# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Рейтинг платёжной дисциплины клиентов по истории поступлений.

Правила, а не ML: каждую оценку можно объяснить предпринимателю одной фразой.
Пороги сравнивают клиента прежде всего с его собственной нормой — для элеватора
70 дней от УПД может быть обычным делом, а для дистрибьютора — тревожным сигналом.
Все расчёты используют только операции с датой <= as_of.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Literal

from .dataset import Operation
from .documents import PurposeInfo, parse_purpose

METHOD_VERSION = "counterparty-rating-0.2"

Grade = Literal["A", "B", "C", "D"]

GRADE_LABELS: dict[str, str] = {
    "A": "Платит быстро и стабильно",
    "B": "Платит долго, но предсказуемо",
    "C": "Нестабилен или стал платить медленнее",
    "D": "Риск потери клиента: давно нет оплат",
}
# Порядок вывода: сначала то, что требует внимания.
_GRADE_ORDER = {"D": 0, "C": 1, "B": 2, "A": 3}


@dataclass(frozen=True, slots=True)
class RatingConfig:
    """Пороги рейтинга. Стартовые значения выбраны по распределению датасета и подлежат
    проверке backtest'ом; это настройки, а не установленная истина."""

    min_documented_payments: int = 5  # меньше — о норме клиента говорить рано
    recent_window: int = 4  # сколько последних оплат сравниваем с нормой
    drift_days: int = 15  # «стал платить медленнее» на столько дней
    spread_days: int = 40  # ширина коридора p10..p90, выше — нестабилен
    partial_share: float = 0.25  # доля частичных оплат, выше — нестабилен
    slow_lag_days: int = 14  # медиана выше — «платит долго»
    silence_min_days: int = 60  # тишина короче не считается потерей
    silence_gap_factor: float = 2.0  # тишина дольше 2× обычного «длинного» перерыва
    revenue_window_days: int = 365  # окно для доли в выручке и активности клиента
    major_client_share: float = 0.10  # от этой доли клиент считается крупным
    max_lag_days: int = 365  # больше — скорее ошибка в назначении, чем задержка
    min_history_days: int = 90
    # Ранний сигнал ухода (до D). Выбран по validation-срезам 2025 года, см. reports/.
    early_silence_factor: float = 1.5  # R1: тишина ≥ 1.5× обычного «длинного» перерыва
    early_volume_window_days: int = 90  # R2: сравниваем последние 90 дней с предыдущими 90
    early_volume_drop: float = 0.5  # R2: заплатил меньше половины прежнего
    early_min_gaps: int = 3  # меньше перерывов — ритм клиента ещё не известен


@dataclass(frozen=True, slots=True)
class EarlyWarning:
    """Ранний сигнал ухода клиента. Это «присмотритесь», а не прогноз: по backtest'у
    сбывается примерно каждая четвёртая тревога, поэтому оценку A–D он не меняет."""

    level: Literal["watch"]
    rules: list[str]  # silence_vs_rhythm | volume_drop
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class CounterpartyRating:
    counterparty_key: str
    counterparty_inn: str | None
    counterparty_name: str | None
    grade: Grade
    grade_label: str
    payments_count: int
    documented_payments_count: int
    lag_days_median: float
    lag_days_p90: int
    recent_lag_days_median: float | None
    lag_drift_days: float | None
    partial_share: float
    received_minor: int  # получено за окно revenue_window_days
    revenue_share: float
    last_payment_date: date
    days_since_last_payment: int
    typical_interval_days: float | None
    reasons: list[str]
    early_warning: EarlyWarning | None = None


@dataclass(slots=True)
class RatingReport:
    company_id: str
    as_of: date
    method_version: str
    applicable: bool
    clients: list[CounterpartyRating] = field(default_factory=list)
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


@dataclass(slots=True)
class ClientPayment:
    op: Operation
    info: PurposeInfo


def counterparty_key(op: Operation) -> str | None:
    # ИНН надёжнее названия: название бывает записано по-разному. Без обоих — не клиент.
    if op.counterparty_inn:
        return f"inn:{op.counterparty_inn}"
    if op.counterparty_name:
        return f"name:{op.counterparty_name.strip().lower()}"
    return None


def _quantile(values: list[int], q: float) -> int:
    # Ближайший ранг без интерполяции: пользователю показываем реально случившиеся дни.
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _p90(values: list[int]) -> int:
    return _quantile(values, 0.9)


def payment_lag_days(payment: ClientPayment, cfg: RatingConfig) -> int | None:
    """Дни от документа до оплаты или None, если задержку по этой оплате измерить нельзя."""
    doc = payment.info.document
    if doc is None or payment.info.prepayment:
        return None  # предоплата до документа — не задержка
    lag = (payment.op.op_date - doc.doc_date).days
    return lag if 0 <= lag <= cfg.max_lag_days else None


def split_incoming(
    operations: Iterable[Operation],
) -> tuple[dict[str, list[ClientPayment]], list[Operation], dict[str, int]]:
    """Делит поступления на оплаты клиентов (по ключу), всю операционную выручку и служебные.

    Возвращает (оплаты по клиентам, операционные поступления, счётчик исключённых по причинам).
    Даты не фильтрует — это делает вызывающий код.
    """
    by_client: dict[str, list[ClientPayment]] = defaultdict(list)
    operating: list[Operation] = []
    excluded: dict[str, int] = defaultdict(int)
    for op in operations:
        if op.direction != "in":
            continue
        info = parse_purpose(op.purpose)
        if info.non_operating:
            # Займы, свои переводы и возвраты — не выручка и не поведение клиента.
            excluded[info.non_operating] += 1
            continue
        operating.append(op)
        key = counterparty_key(op)
        if key is not None:
            by_client[key].append(ClientPayment(op, info))
    for payments in by_client.values():
        payments.sort(key=lambda p: (p.op.op_date, p.op.operation_id))
    return by_client, operating, excluded


def _round(value: float, digits: int = 3) -> float:
    return round(value, digits)


def _days(value: float) -> str:
    return f"{value:g} дн."


def rate_counterparties(
    operations: Iterable[Operation],
    company_id: str,
    as_of: date,
    config: RatingConfig | None = None,
) -> RatingReport:
    cfg = config or RatingConfig()
    report = RatingReport(company_id=company_id, as_of=as_of, method_version=METHOD_VERSION, applicable=False)

    history = [op for op in operations if op.op_date <= as_of]  # будущее не видим
    if not history:
        report.warnings.append("Нет операций до даты среза — рейтинг клиентов не построить.")
        return report
    if (as_of - min(op.op_date for op in history)).days < cfg.min_history_days:
        report.warnings.append(f"История короче {cfg.min_history_days} дней — оценки клиентов ненадёжны.")

    window_start = as_of - timedelta(days=cfg.revenue_window_days)
    by_client, operating, excluded = split_incoming(history)
    operating_revenue = sum(op.amount_minor for op in operating if op.op_date > window_start)

    ratings: list[CounterpartyRating] = []
    skipped_few = 0
    skipped_inactive = 0
    for key, payments in by_client.items():
        rating = _rate_client(key, payments, as_of, window_start, operating_revenue, cfg)
        if rating == "few":
            skipped_few += 1
        elif rating == "inactive":
            skipped_inactive += 1
        elif rating is not None:
            ratings.append(rating)

    ratings.sort(key=lambda r: (_GRADE_ORDER[r.grade], -r.received_minor))
    report.clients = ratings
    report.applicable = bool(ratings)
    rated_revenue = sum(r.received_minor for r in ratings)
    report.summary = {
        "rated_clients": len(ratings),
        "early_warnings": sum(r.early_warning is not None for r in ratings),
        "grades": {g: sum(r.grade == g for r in ratings) for g in ("A", "B", "C", "D")},
        "operating_revenue_minor": operating_revenue,
        # Какую часть выручки вообще покрывает рейтинг — честная граница применимости.
        "rated_revenue_share": _round(rated_revenue / operating_revenue) if operating_revenue else 0.0,
        "skipped_few_documented_payments": skipped_few,
        "skipped_inactive_clients": skipped_inactive,
        "excluded_non_operating": dict(excluded),
    }
    if not ratings:
        report.warnings.append(
            "Поступления почти не привязаны к документам (эквайринг, СБП, наличные) — "
            "рейтинг клиентов для этой компании неприменим."
        )
    return report


def _rate_client(
    key: str,
    payments: list[ClientPayment],
    as_of: date,
    window_start: date,
    operating_revenue: int,
    cfg: RatingConfig,
) -> CounterpartyRating | Literal["few", "inactive"] | None:
    lags = [lag for p in payments if (lag := payment_lag_days(p, cfg)) is not None]
    if len(lags) < cfg.min_documented_payments:
        return "few"

    last = payments[-1].op
    if last.op_date <= window_start:
        return "inactive"  # ушёл больше года назад: уже история, а не текущий риск

    median = statistics.median(lags)
    p90 = _p90(lags)
    p10 = _quantile(lags, 0.1)
    recent_median: float | None = None
    drift: float | None = None
    if len(lags) >= 2 * cfg.recent_window:
        recent_median = statistics.median(lags[-cfg.recent_window :])
        drift = recent_median - statistics.median(lags[: -cfg.recent_window])

    dates = sorted({p.op.op_date for p in payments})
    gaps = [(b - a).days for a, b in itertools.pairwise(dates)]
    typical_interval = statistics.median(gaps) if gaps else None
    since_last = (as_of - last.op_date).days
    silence_limit = max(cfg.silence_min_days, cfg.silence_gap_factor * _p90(gaps)) if gaps else cfg.silence_min_days

    received = sum(p.op.amount_minor for p in payments if p.op.op_date > window_start)
    share = received / operating_revenue if operating_revenue else 0.0
    partial = sum(p.info.partial for p in payments) / len(payments)

    reasons = [f"Обычно оплачивает через {_days(median)} после документа; 90% оплат — не позже {_days(p90)}"]
    silent = since_last > silence_limit
    drifting = drift is not None and drift >= cfg.drift_days
    # Коридор p10..p90, а не p90 − медиана: клиент «то 5, то 60 дней» тоже непредсказуем.
    unstable = p90 - p10 >= cfg.spread_days
    partial_heavy = partial >= cfg.partial_share
    if silent:
        reasons.append(f"Нет оплат {_days(since_last)}, хотя обычно платит раз в {_days(typical_interval or 0)}")
    if drifting:
        reasons.append(f"Последние {cfg.recent_window} оплаты медленнее обычного на {_days(drift)}")
    if unstable:
        reasons.append(f"Сроки оплаты сильно скачут: от {_days(p10)} до {_days(p90)}")
    if partial_heavy:
        reasons.append(f"Часто платит частями: {partial:.0%} оплат частичные")
    if share >= cfg.major_client_share:
        reasons.append(f"Крупный клиент: {share:.0%} поступлений за год")

    early = None if silent else _early_warning(payments, as_of, gaps, since_last, cfg)

    grade: Grade
    if silent:
        grade = "D"
    elif drifting or unstable or partial_heavy:
        grade = "C"
    elif median > cfg.slow_lag_days:
        grade = "B"
    else:
        grade = "A"

    return CounterpartyRating(
        counterparty_key=key,
        counterparty_inn=last.counterparty_inn,
        counterparty_name=last.counterparty_name,
        grade=grade,
        grade_label=GRADE_LABELS[grade],
        payments_count=len(payments),
        documented_payments_count=len(lags),
        lag_days_median=float(median),
        lag_days_p90=p90,
        recent_lag_days_median=float(recent_median) if recent_median is not None else None,
        lag_drift_days=float(drift) if drift is not None else None,
        partial_share=_round(partial),
        received_minor=received,
        revenue_share=_round(share),
        last_payment_date=last.op_date,
        days_since_last_payment=since_last,
        typical_interval_days=float(typical_interval) if typical_interval is not None else None,
        reasons=reasons,
        early_warning=early,
    )


def _early_warning(
    payments: list[ClientPayment],
    as_of: date,
    gaps: list[int],
    since_last: int,
    cfg: RatingConfig,
) -> EarlyWarning | None:
    """R1: молчит заметно дольше своего ритма. R2: молчит дольше обычного и платит вдвое меньше.

    Опираемся на p90 перерывов, а не на медиану: клиент с неровным ритмом не должен
    поднимать тревогу из-за одной обычной паузы.
    """
    if len(gaps) < cfg.early_min_gaps:
        return None
    long_gap = _p90(gaps)
    rules: list[str] = []
    reasons: list[str] = []
    if since_last >= cfg.early_silence_factor * long_gap:
        rules.append("silence_vs_rhythm")
        reasons.append(f"Не платит {_days(since_last)} — обычно перерыв не дольше {_days(long_gap)}")

    window = timedelta(days=cfg.early_volume_window_days)
    recent = sum(p.op.amount_minor for p in payments if p.op.op_date > as_of - window)
    previous = sum(p.op.amount_minor for p in payments if as_of - 2 * window < p.op.op_date <= as_of - window)
    if since_last >= long_gap and previous > 0 and recent < cfg.early_volume_drop * previous:
        rules.append("volume_drop")
        reasons.append(
            f"За последние {cfg.early_volume_window_days} дн. заплатил на "
            f"{1 - recent / previous:.0%} меньше, чем за предыдущие"
        )
    if not rules:
        return None
    return EarlyWarning(level="watch", rules=rules, reasons=reasons)

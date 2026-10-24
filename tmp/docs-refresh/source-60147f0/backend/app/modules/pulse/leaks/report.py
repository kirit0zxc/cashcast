# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Отчёт «Где утекают деньги» по выписке одной компании."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from ..advisor.dataset import Operation
from .benchmarks import load_benchmarks, peer_stats
from .detectors import DETECTORS, Context
from .model import Finding, LeakConfig, LeakReport
from .quality import drop_export_duplicates

METHOD_VERSION = "leaks-0.1"
_NATURE_ORDER = {"loss": 0, "opportunity": 0, "signal": 1, "frozen": 2}


def _sort_key(f: Finding) -> tuple:
    # Сначала потери и упущенный доход по величине, затем сигналы «проверьте», в конце —
    # замороженные деньги.
    return (_NATURE_ORDER[f.nature], -f.amount_minor)


def build_report(
    operations: Sequence[Operation],
    company_id: str,
    as_of: date,
    industry: str | None = None,
    bench: dict | None = None,
    cfg: LeakConfig | None = None,
    *,
    deduplicate: bool = True,
    balances: dict[date, int] | None = None,
) -> LeakReport:
    cfg = cfg or LeakConfig()
    history = [op for op in operations if op.op_date <= as_of]  # будущее не видим
    history, duplicates = drop_export_duplicates(history) if deduplicate else (history, 0)
    window_start = as_of - timedelta(days=cfg.window_days)
    report = LeakReport(
        company_id=company_id, as_of=as_of, window_start=window_start, method_version=METHOD_VERSION, industry=industry
    )
    if not history:
        report.warnings.append("Нет операций до даты анализа.")
        return report
    if duplicates:
        report.warnings.append(f"Убрано строк-дублей выгрузки: {duplicates} — остаток дня сходится без них.")
    window_ops = [op for op in history if op.op_date > window_start]
    covered = (as_of - max(window_start, history[0].op_date - timedelta(days=1))).days
    annual_factor = cfg.window_days / covered if covered > 0 else 1.0
    if covered < cfg.window_days:
        report.warnings.append(
            f"История короче года ({covered} дн.): годовые суммы пересчитаны пропорционально и менее надёжны."
        )
    bench = bench if bench is not None else load_benchmarks()
    peers = peer_stats(bench, industry)
    ctx = Context(
        as_of=as_of,
        window_start=window_start,
        ops=history,
        window_ops=window_ops,
        annual_factor=annual_factor,
        peers=peers,
        cfg=cfg,
        balances=balances,
    )
    for detector in DETECTORS:
        report.findings.extend(detector(ctx))
    report.findings.sort(key=_sort_key)

    def total(nature: str, period: str, certainty: str | None = None) -> int:
        return sum(
            f.amount_minor
            for f in report.findings
            if f.nature == nature and f.period == period and (certainty is None or f.certainty == certainty)
        )

    report.totals = {
        "loss_per_year_minor": total("loss", "year"),
        "opportunity_per_year_minor": total("opportunity", "year"),
        "one_off_loss_window_minor": total("loss", "window"),
        "frozen_window_minor": total("frozen", "window"),
        "signals": sum(1 for f in report.findings if f.nature == "signal"),
    }
    report.assumptions = [
        f"Анализ за последние {cfg.window_days} дн. до {as_of:%d.%m.%Y}.",
        f"Ставка для свободного остатка — {cfg.deposit_rate_annual:.0%} годовых (оценка).",
        f"На СБП переходит {cfg.sbp_shift_share:.0%} карточных оплат (оценка).",
        f"На депозит предлагается {cfg.idle_safe_share:.0%} неснижаемого остатка — остальное запас.",
        f"Рост регулярного платежа меньше {cfg.price_growth_threshold:.0%} в год считается обычной индексацией.",
        f"Сравнение с похожими бизнесами: {peers.scope} (датасет участников, синтетика).",
    ]
    return report

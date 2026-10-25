# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Находка аудитора, отчёт и настройки."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

Certainty = Literal["fact", "estimate"]
Period = Literal["year", "window"]  # ₽ в год (повторяется) или разово за окно анализа
# потеря, упущенный доход, сигнал «проверьте» (в денежные итоги не входит), замороженные деньги
Nature = Literal["loss", "opportunity", "signal", "frozen"]


@dataclass(frozen=True, slots=True)
class LeakConfig:
    """Допущения утверждены командой; меняются здесь, а не в коде детекторов."""

    window_days: int = 365  # анализируем последний год
    deposit_rate_annual: float = 0.12  # ставка для простаивающего остатка, «уточните в банке»
    idle_min_minor: int = 10_000_000  # меньше 100 тыс. ₽ размещать нет смысла
    idle_min_months: int = 6  # меньше полугода истории — не делаем вывод о «неснижаемом»
    idle_safe_share: float = 0.5  # разместить половину минимума; см. reports/validation.md
    sbp_shift_share: float = 0.30  # реалистичная доля карточных оплат, переводимая на СБП
    rate_tolerance: float = 0.0005  # 0.05 п.п. — разницу меньше не считаем переплатой
    price_growth_threshold: float = 0.10  # рост меньше 10% в год — обычная индексация
    duplicate_refund_days: int = 30  # дубль, за которым пришёл возврат, — не потеря


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    nature: Nature
    certainty: Certainty
    title: str
    amount_minor: int  # ₽ в копейках за period
    period: Period
    evidence: list[str]  # почему мы так считаем — цифрами
    action: str  # что сделать предпринимателю
    details: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class LeakReport:
    company_id: str
    as_of: date
    window_start: date
    method_version: str
    industry: str | None
    findings: list[Finding] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
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


def rub(minor: int) -> str:
    return f"{minor / 100:,.0f} ₽".replace(",", " ")


def pct(rate: float) -> str:
    return f"{rate * 100:.2f}%"

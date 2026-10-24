# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Классификация списаний: что за платёж и можно ли его сдвинуть ради спасения от разрыва.

Гибкость — главное для плана спасения:
- hard     — переносить нельзя: налоги, зарплата, кредиты, аренда, коммуналка, взыскания;
- regular  — регулярные расходы бизнеса, перенос нежелателен (бухгалтерия, топливо, реклама);
- flexible — поставщики и разовые покупки, перенос возможен в пределах своей истории;
- owner    — деньги владельца (дивиденды, вывод на карту, возврат займа учредителю):
             отложить бесплатно, решает сам предприниматель;
- internal — перевод на свой счёт в другом банке: деньги не тратятся, их можно вернуть.

Правила — регулярные выражения по назначению платежа; порядок важен, срабатывает первое.
Если назначение пустое, классифицируем по названию контрагента с пометкой matched_by.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

from .dataset import Operation

Flexibility = Literal["hard", "regular", "flexible", "owner", "internal", "unknown"]
MatchedBy = Literal["purpose", "counterparty", "none"]


@dataclass(frozen=True, slots=True)
class OutflowClass:
    kind: str
    flexibility: Flexibility
    backend_category: str  # словарь Category основного проекта CashCast
    matched_by: MatchedBy


# kind -> (гибкость, категория основного проекта).
KINDS: dict[str, tuple[Flexibility, str]] = {
    "internal_transfer": ("internal", "transfer"),
    "owner_withdrawal": ("owner", "other"),
    "enforcement": ("hard", "other"),
    "tax": ("hard", "tax"),
    "payroll": ("hard", "payroll"),
    "loan": ("hard", "loan"),
    "fees": ("hard", "fees"),
    "rent": ("hard", "rent"),
    "utilities": ("hard", "other"),
    "marketing": ("regular", "other"),
    "services": ("regular", "other"),
    "fuel_transport": ("regular", "purchases"),
    "capex": ("flexible", "purchases"),
    "purchases": ("flexible", "purchases"),
    "other": ("unknown", "other"),
}


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Порядок важен: «Перевод собственных средств на личную карту» — это вывод владельцем,
# а не внутренний перевод; «ремонт автомобиля» — услуга, а не покупка автомобиля.
_PURPOSE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "owner_withdrawal",
        _rx(
            r"дивиденд|на личн\w+\s+(сч[её]т|карту)|средств\w*\s+ИП\s+на\s+сч[её]т\s+физическ"
            r"|возврат\w*\s+.*займа\s+учредител"
        ),
    ),
    (
        "internal_transfer",
        _rx(
            r"собственных\s+средств\s+на\s+расч[её]тный\s+сч[её]т"
            r"|остатка\s+денежных\s+средств\s+в\s+связи\s+с\s+закрытием"
        ),
    ),
    ("enforcement", _rx(r"исполнительн\w+\s+лист")),
    ("tax", _rx(r"\bЕНП\b|единый\s+налоговый\s+плат|налогового\s+органа|страхов\w+\s+взнос")),
    ("payroll", _rx(r"заработн\w+\s+плат|\bГПХ\b|отпускн|больничн")),
    ("loan", _rx(r"кредит|лизинг|овердрафт")),
    ("fees", _rx(r"комисси|POS-терминал|ведени\w+\s+сч[её]та")),
    ("rent", _rx(r"аренд|обеспечительн\w+\s+плат")),
    (
        "utilities",
        _rx(
            r"электроэнерги|водоснабжени|водоотведени|\bТКО\b|услуг\w*\s+связи|интернет"
            r"|теплоснабжени|коммунальн"
        ),
    ),
    ("marketing", _rx(r"реклам")),
    (
        "services",
        _rx(
            r"бухгалтерск|уборк|охран|подписк|програмн|облачн|обслуживани\w+\s+бассейн"
            r"|ремонт\s+автомобил"
        ),
    ),
    ("fuel_transport", _rx(r"топливн|провоза\s+по\s+дорогам|расч[её]тной\s+записи")),
    ("capex", _rx(r"оборудовани|за\s+автомобиль|ремонт\s+помещени")),
    (
        "purchases",
        _rx(
            r"\bУПД\b|сч[её]т|товар|продукц|материал|субподряд|экспедицион|фулфилмент|хранени"
            r"|запчаст|поставк|изделия|продукт|постав"
        ),
    ),
)

# Запасной путь для пустых назначений: по названию получателя.
_COUNTERPARTY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("owner_withdrawal", _rx(r"учредител|участник\s+общества")),
    ("tax", _rx(r"казначейство|\bФНС\b")),
    ("fees", _rx(r"\bбанк\b")),
    ("payroll", _rx(r"сотрудник|самозанят")),
    ("utilities", _rx(r"энергосбыт|телеком|водоканал")),
    ("marketing", _rx(r"реклам")),
    ("purchases", _rx(r"^(ООО|АО|ПАО|ИП)\b")),
)


def _build(kind: str, matched_by: MatchedBy) -> OutflowClass:
    flexibility, category = KINDS[kind]
    return OutflowClass(kind=kind, flexibility=flexibility, backend_category=category, matched_by=matched_by)


@lru_cache(maxsize=65536)
def classify_text(purpose: str | None, counterparty_name: str | None) -> OutflowClass:
    if purpose and purpose.strip():
        for kind, pattern in _PURPOSE_RULES:
            if pattern.search(purpose):
                return _build(kind, "purpose")
        return _build("other", "none")
    if counterparty_name:
        for kind, pattern in _COUNTERPARTY_RULES:
            if pattern.search(counterparty_name):
                return _build(kind, "counterparty")
    return _build("other", "none")


def classify_outflow(op: Operation) -> OutflowClass:
    if op.direction != "out":
        raise ValueError("классифицируются только списания")
    return classify_text(op.purpose, op.counterparty_name)


def summarize_outflows(operations: Iterable[Operation], as_of: date, window_days: int = 90) -> dict:
    """Структура списаний за окно (as_of − window_days, as_of]: суммы по гибкости и видам.

    Отвечает на вопрос плана спасения «из чего вообще состоят расходы и сколько из них
    можно двигать». Только данные до as_of.
    """
    start = as_of - timedelta(days=window_days)
    by_flex: dict[str, int] = defaultdict(int)
    by_kind: dict[str, int] = defaultdict(int)
    total = 0
    for op in operations:
        if op.direction != "out" or not (start < op.op_date <= as_of):
            continue
        cls = classify_outflow(op)
        by_flex[cls.flexibility] += op.amount_minor
        by_kind[cls.kind] += op.amount_minor
        total += op.amount_minor
    return {
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "total_minor": total,
        "by_flexibility_minor": dict(sorted(by_flex.items(), key=lambda kv: -kv[1])),
        "by_kind_minor": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "share_by_flexibility": {k: round(v / total, 3) for k, v in by_flex.items()} if total else {},
    }

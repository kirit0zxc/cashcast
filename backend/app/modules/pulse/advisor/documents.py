# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Разбор назначения платежа: ссылка на документ (УПД/счёт/акт/накладная) и служебные потоки.

Дата документа — опора для измерения задержки оплаты: «Оплата по УПД № 279 от 19.08.2024»,
пришедшая 02.10.2024, значит клиент платил 44 дня. Это не срок по договору (его в данных нет),
а фактическое время от документа до денег.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

# Только документы отгрузки/выставления. Договор сюда намеренно не входит: дата договора
# говорит о начале отношений, а не о том, когда клиент должен был заплатить.
_DOC_RE = re.compile(
    r"\b(?P<kind>УПД|сч[её]т[уа]?|акт[уа]?|(?:товарн\w*\s+)?накладн\w*|ТТН)"
    r"\s*(?:№\s*)?(?P<number>[\w\-/]+)\s+от\s+"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})",
    re.IGNORECASE,
)
_PARTIAL_RE = re.compile(r"частичн", re.IGNORECASE)
_PREPAYMENT_RE = re.compile(r"\b(предоплат|аванс)", re.IGNORECASE)

# Поступления, которые не являются оплатой клиента: их нельзя ни считать выручкой,
# ни использовать для задержек. Порядок важен: возврат проверяется первым, потому что
# «Возврат платежа … Оплата по УПД № …» содержит ссылку на НАШ документ, а не клиента.
_NON_OPERATING: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("refund", re.compile(r"возврат\s+(платежа|ошибочн)|ошибочно\s+перечисл", re.IGNORECASE)),
    ("own_transfer", re.compile(r"собственн\w*\s+средств", re.IGNORECASE)),
    ("loan", re.compile(r"\bзайм|\bкредит", re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class DocumentRef:
    kind: str  # upd | invoice | act | waybill
    number: str
    doc_date: date


@dataclass(frozen=True, slots=True)
class PurposeInfo:
    document: DocumentRef | None
    partial: bool
    prepayment: bool
    non_operating: str | None  # refund | own_transfer | loan | None


def _kind(raw: str) -> str:
    low = raw.lower()
    if low == "упд":
        return "upd"
    if low.startswith("сч"):
        return "invoice"
    if low.startswith("акт"):
        return "act"
    return "waybill"


def parse_document(purpose: str | None) -> DocumentRef | None:
    """Первая ссылка на документ с корректной датой или None."""
    if not purpose:
        return None
    for m in _DOC_RE.finditer(purpose):
        try:
            doc_date = date(int(m["year"]), int(m["month"]), int(m["day"]))
        except ValueError:
            continue  # «31.02.2025» — опечатка в назначении, ищем дальше
        return DocumentRef(kind=_kind(m["kind"]), number=m["number"], doc_date=doc_date)
    return None


def non_operating_reason(purpose: str | None) -> str | None:
    if not purpose:
        return None
    for reason, pattern in _NON_OPERATING:
        if pattern.search(purpose):
            return reason
    return None


# Кэш: backtest разбирает одни и те же назначения на каждом срезе. PurposeInfo неизменяем.
@lru_cache(maxsize=65536)
def parse_purpose(purpose: str | None) -> PurposeInfo:
    text = purpose or ""
    return PurposeInfo(
        document=parse_document(purpose),
        partial=bool(_PARTIAL_RE.search(text)),
        prepayment=bool(_PREPAYMENT_RE.search(text)),
        non_operating=non_operating_reason(purpose),
    )

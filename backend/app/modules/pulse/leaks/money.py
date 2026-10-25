# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Суммы внутри назначения платежа и комиссии каналов приёма оплаты.

В назначениях суммы пишут по-разному: «2861-52», «1 234.56», «1234,56». Комиссию банк
указывает прямо в зачислении: «Зачисление средств по операциям эквайринга … Сумма
операций 2861-52, комиссия 51-47» или «…через СБП (QR-код) … Сумма 1551-73, комиссия 6-88».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Channel = Literal["card", "sbp"]

_AMOUNT = r"\d[\d  ]*[.,-]\d{2}"
_COMMISSION_RE = re.compile(
    rf"Сумма(?:\s+операций)?\s+(?P<gross>{_AMOUNT}),\s*комисси\w*\s+(?P<fee>{_AMOUNT})",
    re.IGNORECASE,
)
_CARD_RE = re.compile(r"эквайринг", re.IGNORECASE)
_SBP_RE = re.compile(r"\bСБП\b|QR-код", re.IGNORECASE)


def parse_amount_minor(text: str) -> int:
    """'2861-52' / '1 234.56' / '1234,56' -> копейки. Целые числа без копеек не принимаем:
    в назначениях они обычно номера документов, а не суммы."""
    m = re.fullmatch(r"(\d[\d  ]*)[.,-](\d{2})", text.strip())
    if not m:
        raise ValueError("не распознана сумма в назначении")
    rubles = int(re.sub(r"[  ]", "", m.group(1)))
    return rubles * 100 + int(m.group(2))


@dataclass(frozen=True, slots=True)
class ChannelCommission:
    channel: Channel
    gross_minor: int  # оборот покупателей до комиссии
    fee_minor: int


def parse_commission(purpose: str | None) -> ChannelCommission | None:
    """Комиссия банка из назначения зачисления по эквайрингу или СБП; иначе None."""
    if not purpose:
        return None
    if _CARD_RE.search(purpose):
        channel: Channel = "card"
    elif _SBP_RE.search(purpose):
        channel = "sbp"
    else:
        return None
    m = _COMMISSION_RE.search(purpose)
    if not m:
        return None
    gross = parse_amount_minor(m["gross"])
    fee = parse_amount_minor(m["fee"])
    if gross <= 0 or fee < 0 or fee > gross:
        return None  # явная ошибка разбора — не делаем из неё выводов
    return ChannelCommission(channel, gross, fee)

"""Адаптер: строки таблиц основного проекта CashCast -> Operation пакета pulse.

Не импортирует ничего из основного проекта: принимает любые объекты или словари с полями
как у ORM bank_transaction и daily_balance (на 24.10.2026):
- операция: id, booked_on, amount_minor, direction ('in'|'out'), counterparty_ref (ИНН или
  нормализованное имя), counterparty_name, purpose;
- остаток: balance_date, closing_balance_minor.
Остаток дня проставляется всем операциям этого дня — так же, как в выписке датасета.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .advisor.dataset import Operation


def _get(row: Any, name: str):
    return row[name] if isinstance(row, dict) else getattr(row, name)


def operations_from_records(
    company_id: str,
    transactions: Iterable[Any],
    daily_balances: Iterable[Any] = (),
) -> list[Operation]:
    balance: dict[date, int] = {_get(b, "balance_date"): int(_get(b, "closing_balance_minor")) for b in daily_balances}
    ops = []
    for t in transactions:
        direction = str(_get(t, "direction"))
        if direction not in ("in", "out"):
            raise ValueError("direction должен быть 'in' или 'out'")
        day = _get(t, "booked_on")
        ops.append(
            Operation(
                company_id=company_id,
                operation_id=str(_get(t, "id")),
                op_date=day,
                amount_minor=int(_get(t, "amount_minor")),
                direction=direction,  # type: ignore[arg-type]
                counterparty_inn=_get(t, "counterparty_ref") or None,
                counterparty_name=_get(t, "counterparty_name") or None,
                purpose=_get(t, "purpose") or None,
                balance_eod_minor=balance.get(day),
            )
        )
    ops.sort(key=lambda o: (o.op_date, o.operation_id))
    return ops

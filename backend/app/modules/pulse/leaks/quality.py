# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Дубли строк выгрузки, доказанные остатком дня.

README датасета предупреждает о «единичных дублях строк». Их нельзя путать с настоящей
двойной оплатой: ручная сверка показала, что 6 из 7 «двойных платежей» — повтор строки
в выгрузке. Различаем по остатку: если остаток предыдущего дня плюс движение дня сходится
с остатком конца дня только без лишних копий — копии не настоящие, их убираем. Если день
сходится со всеми копиями — платежи реальные. Если проверить нечем (первый день, нет
остатков) — ничего не трогаем.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from ..advisor.dataset import Operation


def _signature(op: Operation) -> tuple:
    return (op.op_date, op.direction, op.amount_minor, op.counterparty_inn, op.counterparty_name, op.purpose)


def _net(ops: Sequence[Operation]) -> int:
    return sum(op.amount_minor if op.direction == "in" else -op.amount_minor for op in ops)


def drop_export_duplicates(operations: Sequence[Operation]) -> tuple[list[Operation], int]:
    """(операции без доказанных дублей выгрузки, сколько строк убрано)."""
    by_day: dict[date, list[Operation]] = defaultdict(list)
    for op in operations:
        by_day[op.op_date].append(op)
    days = sorted(by_day)
    eod = {
        d: next((op.balance_eod_minor for op in reversed(by_day[d]) if op.balance_eod_minor is not None), None)
        for d in days
    }
    removed: set[str] = set()
    for prev, day in itertools.pairwise(days):
        ops = by_day[day]
        groups: dict[tuple, list[Operation]] = defaultdict(list)
        for op in ops:
            groups[_signature(op)].append(op)
        extra = [op for g in groups.values() if len(g) > 1 for op in g[1:]]
        if not extra or eod[prev] is None or eod[day] is None:
            continue
        with_all = eod[prev] + _net(ops)
        without = with_all - _net(extra)
        if with_all != eod[day] and without == eod[day]:
            removed.update(op.operation_id for op in extra)
    kept = [op for op in operations if op.operation_id not in removed]
    return kept, len(removed)

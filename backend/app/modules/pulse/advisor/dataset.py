# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""Чтение выписок датасета организаторов в операции с суммами в копейках."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

Direction = Literal["in", "out"]

# Значения колонки direction в датасете. Неизвестное значение — ошибка, а не «по умолчанию
# списание»: иначе тихо перевернём знак выручки.
_DIRECTIONS: dict[str, Direction] = {"Поступление": "in", "Списание": "out"}


class DatasetError(ValueError):
    """Строка выписки не соответствует формату датасета."""


@dataclass(frozen=True, slots=True)
class Operation:
    company_id: str
    operation_id: str
    op_date: date
    amount_minor: int  # всегда > 0, знак задаёт direction
    direction: Direction
    counterparty_inn: str | None  # строка: вымышленные ИНН начинаются с нулей
    counterparty_name: str | None
    purpose: str | None
    balance_eod_minor: int | None


def parse_amount_minor(raw: str) -> int:
    """'12345.67' -> 1234567. Decimal, а не float: копейки не должны «плыть»."""
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise DatasetError("не распознана сумма") from exc
    minor = value * 100
    if minor != minor.to_integral_value():
        raise DatasetError("сумма точнее копейки")
    return int(minor)


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_row(row: dict[str, str]) -> Operation:
    direction = _DIRECTIONS.get((row.get("direction") or "").strip())
    if direction is None:
        raise DatasetError("неизвестное направление операции")
    amount = parse_amount_minor(row["amount"])
    if amount <= 0:
        raise DatasetError("сумма должна быть положительной")
    balance_raw = _blank_to_none(row.get("balance_eod"))
    return Operation(
        company_id=row["company_id"].strip(),
        operation_id=row["operation_id"].strip(),
        op_date=date.fromisoformat(row["operation_date"].strip()),
        amount_minor=amount,
        direction=direction,
        counterparty_inn=_blank_to_none(row.get("counterparty_inn")),
        counterparty_name=_blank_to_none(row.get("counterparty_name")),
        purpose=_blank_to_none(row.get("payment_purpose")),
        balance_eod_minor=parse_amount_minor(balance_raw) if balance_raw else None,
    )


def read_operations(path: Path) -> Iterator[Operation]:
    # utf-8-sig снимает BOM; все поля читаем строками, чтобы не потерять нули в ИНН.
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for line_no, row in enumerate(csv.DictReader(fh, delimiter=";"), start=2):
            try:
                yield parse_row(row)
            except (DatasetError, KeyError, ValueError) as exc:
                # В сообщение не попадает содержимое строки — только номер и причина.
                raise DatasetError(f"{path.name}, строка {line_no}: {exc}") from exc


def load_company(data_dir: Path, company_id: str) -> list[Operation]:
    """Операции одной компании из statements/<id>.csv, отсортированные по дате.

    Дубли по operation_id отбрасываются: README датасета предупреждает о единичных дублях строк.
    """
    path = data_dir / "statements" / f"{company_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"нет выписки компании {company_id}")
    seen: set[str] = set()
    ops: list[Operation] = []
    for op in read_operations(path):
        if op.operation_id in seen:
            continue
        seen.add(op.operation_id)
        ops.append(op)
    ops.sort(key=lambda o: (o.op_date, o.operation_id))
    return ops

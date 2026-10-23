"""Разбор CSV-выписки с настраиваемым маппингом колонок.

Датасета ещё нет, поэтому имена колонок не захардкожены: их задаёт column_mapping.
Реальные имена подставим после получения данных — схему под догадку не подгоняем.

Деньги парсим в целые копейки через Decimal (не float): 1234.56 -> 123456.
Поддерживаем два способа задать направление:
  - одна колонка со знаком суммы (amount: +приток / -отток), либо
  - отдельная колонка direction со значениями из direction_map.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.modules.contracts import Direction

# Форматы дат пробуем по порядку. Расширяемо под реальный банк.
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d")


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Соответствие полей CSV. Любое поле опционально, кроме date и способа задать сумму."""

    date: str
    amount: str | None = None  # колонка со знаковой суммой
    inflow: str | None = None  # либо отдельные колонки прихода/расхода
    outflow: str | None = None
    direction: str | None = None  # либо отдельная колонка направления
    counterparty_name: str | None = None
    counterparty_ref: str | None = None
    purpose: str | None = None
    external_id: str | None = None
    currency: str | None = None
    balance: str | None = None  # остаток на конец дня, если банк его даёт
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    direction_in_values: tuple[str, ...] = ("in", "credit", "приход", "+")
    default_currency: str = "RUB"


@dataclass(frozen=True, slots=True)
class ParsedRow:
    source_row: int
    booked_on: date
    amount_minor: int
    direction: Direction
    currency: str
    counterparty_name: str | None
    counterparty_ref: str | None
    purpose: str | None
    external_id: str | None
    balance_minor: int | None
    fingerprint: str


@dataclass(frozen=True, slots=True)
class RowError:
    source_row: int
    field: str
    message: str


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    # Индексы строк с одинаковым fingerprint внутри файла — кандидаты в дубли, не удаляем молча.
    duplicate_rows: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_date(value: str) -> date:
    v = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не распознана дата: {value!r}")


def _parse_amount_minor(value: str) -> int:
    # Убираем пробелы-разделители тысяч и валютные символы, запятую приводим к точке.
    cleaned = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    cleaned = "".join(c for c in cleaned if c.isdigit() or c in "+-.")
    if not cleaned or cleaned in {"+", "-", "."}:
        raise ValueError(f"не распознана сумма: {value!r}")
    try:
        return int((Decimal(cleaned) * 100).to_integral_value())
    except InvalidOperation as exc:
        raise ValueError(f"не распознана сумма: {value!r}") from exc


def _fingerprint(external_id: str | None, parts: tuple[str, ...]) -> str:
    if external_id:
        return f"ext:{external_id}"
    raw = "|".join(parts)
    return "h:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def parse_statement(content: bytes, mapping: ColumnMapping) -> ParseResult:
    result = ParseResult()
    try:
        text = content.decode(mapping.encoding)
    except UnicodeDecodeError:
        result.errors.append(RowError(0, "file", "Файл не читается в указанной кодировке"))
        return result

    reader = csv.DictReader(io.StringIO(text), delimiter=mapping.delimiter)
    if reader.fieldnames is None:
        result.errors.append(RowError(0, "file", "Пустой файл или нет строки заголовка"))
        return result
    missing = [mapping.date] + (
        [] if (mapping.amount or (mapping.inflow and mapping.outflow)) else ["<сумма>"]
    )
    for col in missing:
        if col and col != "<сумма>" and col not in reader.fieldnames:
            result.errors.append(RowError(0, "mapping", f"Нет колонки {col!r} в заголовке"))
    if result.errors:
        return result

    seen: dict[str, int] = {}
    for idx, raw_row in enumerate(reader, start=1):
        try:
            parsed = _parse_single(idx, raw_row, mapping)
        except ValueError as exc:
            result.errors.append(RowError(idx, "row", str(exc)))
            continue
        if parsed.fingerprint in seen:
            result.duplicate_rows.append(idx)
        else:
            seen[parsed.fingerprint] = idx
        result.rows.append(parsed)
    return result


def _parse_single(idx: int, row: dict[str, str], m: ColumnMapping) -> ParsedRow:
    booked_on = _parse_date(row.get(m.date, ""))

    # Направление и модуль суммы.
    if m.amount:
        signed = _signed_amount(row.get(m.amount, ""))
        direction = Direction.IN if signed >= 0 else Direction.OUT
        amount_minor = abs(signed)
    elif m.inflow or m.outflow:
        inflow = _parse_amount_minor(row[m.inflow]) if m.inflow and row.get(m.inflow) else 0
        outflow = _parse_amount_minor(row[m.outflow]) if m.outflow and row.get(m.outflow) else 0
        if inflow and outflow:
            raise ValueError("в строке заполнены и приход, и расход")
        direction = Direction.IN if inflow else Direction.OUT
        amount_minor = inflow or outflow
    else:  # pragma: no cover — исключено проверкой маппинга выше
        raise ValueError("маппинг не задаёт сумму")

    if m.direction and row.get(m.direction):
        raw_dir = row[m.direction].strip().lower()
        direction = Direction.IN if raw_dir in m.direction_in_values else Direction.OUT

    if amount_minor < 0:
        raise ValueError("отрицательный модуль суммы")

    external_id = (row.get(m.external_id) or "").strip() or None if m.external_id else None
    currency = ((row.get(m.currency) or "").strip() or m.default_currency) if m.currency else m.default_currency
    counterparty_name = (row.get(m.counterparty_name) or "").strip() or None if m.counterparty_name else None
    counterparty_ref = (row.get(m.counterparty_ref) or "").strip() or None if m.counterparty_ref else None
    purpose = (row.get(m.purpose) or "").strip() or None if m.purpose else None
    balance_minor = (
        _signed_amount(row[m.balance]) if m.balance and row.get(m.balance) else None
    )

    fingerprint = _fingerprint(
        external_id,
        (booked_on.isoformat(), str(amount_minor), direction.value, counterparty_ref or "", purpose or ""),
    )
    return ParsedRow(
        source_row=idx,
        booked_on=booked_on,
        amount_minor=amount_minor,
        direction=direction,
        currency=currency,
        counterparty_name=counterparty_name,
        counterparty_ref=counterparty_ref,
        purpose=purpose,
        external_id=external_id,
        balance_minor=balance_minor,
        fingerprint=fingerprint,
    )


def _signed_amount(value: str) -> int:
    v = value.strip()
    # Скобки — бухгалтерская запись отрицательного числа: (200.10) = -200.10.
    neg = v.startswith("-") or (v.startswith("(") and v.endswith(")"))
    magnitude = abs(_parse_amount_minor(v))
    return -magnitude if neg else magnitude

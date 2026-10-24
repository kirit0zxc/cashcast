"""Разбор CSV-выписки с настраиваемым маппингом колонок.

Имена колонок задаёт column_mapping; организаторская выписка использует готовый пресет.

Деньги разбираем из десятичной строки в целые копейки без округления: 1234.56 -> 123456.
Поддерживаем два способа задать направление:
  - одна колонка со знаком суммы (amount: +приток / -отток), либо
  - отдельная колонка direction с известным обозначением прихода/расхода.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.limits import MAX_MONEY_MINOR
from app.modules.contracts import Direction
from app.modules.imports.identity import BankOperationIdentity

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
    direction_in_values: tuple[str, ...] = ("in", "credit", "приход", "поступление", "+")
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
    if not isinstance(value, str):
        raise ValueError("не заполнена дата")
    v = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError("не распознана дата")


def _parse_amount_minor(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("не заполнена сумма")
    cleaned = value.strip()
    parenthesized = cleaned.startswith("(") and cleaned.endswith(")")
    if parenthesized:
        cleaned = cleaned[1:-1].strip()
        if cleaned.startswith(("+", "-")):
            raise ValueError("неоднозначный знак суммы")
    cleaned = re.sub(r"\s*(?:₽|руб\.?|RUB)$", "", cleaned, flags=re.IGNORECASE).strip()
    parsed = re.fullmatch(r"([+-]?)([0-9]+|[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+)(?:[.,]([0-9]{1,2}))?", cleaned)
    if parsed is None:
        raise ValueError("сумма должна быть десятичным числом с максимум двумя знаками")
    sign, whole, fraction = parsed.groups()
    whole = whole.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    # Целые копейки не зависят от Decimal context и не округляют лишние знаки молча.
    amount = int(whole) * 100 + int((fraction or "").ljust(2, "0"))
    if amount > MAX_MONEY_MINOR:
        raise ValueError("сумма превышает допустимый денежный предел")
    return -amount if sign == "-" or parenthesized else amount


def _fingerprint(external_id: str | None, parts: tuple[str, ...]) -> str:
    if external_id:
        if len(external_id) <= 96:
            return f"ext:{external_id}"
        # Длинный банковский ID сохраняем целиком, а ключ укладываем в VARCHAR(100).
        return "ext-h:" + hashlib.sha256(external_id.encode("utf-8")).hexdigest()
    raw = "|".join(parts)
    return "h:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def parse_statement(content: bytes, mapping: ColumnMapping) -> ParseResult:
    result = ParseResult()
    try:
        text = content.decode(mapping.encoding)
    except (UnicodeError, LookupError, TypeError):
        result.errors.append(RowError(0, "file", "Файл не читается в указанной кодировке"))
        return result

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=mapping.delimiter, strict=True)
        headers = reader.fieldnames
    except (csv.Error, TypeError, ValueError):
        result.errors.append(RowError(0, "file", "Некорректный CSV или разделитель"))
        return result
    if headers is None:
        result.errors.append(RowError(0, "file", "Пустой файл или нет строки заголовка"))
        return result
    money_columns = [mapping.amount] if mapping.amount else [mapping.inflow, mapping.outflow]
    required = [mapping.date, mapping.direction, *money_columns]
    if not any(money_columns):
        result.errors.append(RowError(0, "mapping", "Маппинг не задаёт колонку суммы"))
    if len(set(headers)) != len(headers) or any("\x00" in header for header in headers):
        result.errors.append(RowError(0, "mapping", "Повторный или некорректный заголовок"))
    for col in required:
        if col and col not in headers:
            result.errors.append(RowError(0, "mapping", "Нет обязательной колонки в заголовке"))
    if result.errors:
        return result

    seen: dict[str, ParsedRow] = {}
    try:
        for idx, raw_row in enumerate(reader, start=1):
            try:
                if None in raw_row or any(value is None or "\x00" in value for value in raw_row.values()):
                    raise ValueError("неверное число колонок или недопустимый нулевой символ")
                parsed = _parse_single(idx, raw_row, mapping)
            except ValueError as exc:
                result.errors.append(RowError(idx, "row", str(exc)))
                continue
            if parsed.fingerprint in seen:
                if not BankOperationIdentity.matches(seen[parsed.fingerprint], parsed):
                    result.errors.append(RowError(
                        idx, "external_id" if parsed.external_id else "row",
                        "Один ключ операции имеет различающееся содержимое; нужен однозначный банковский ID",
                    ))
                    continue
                result.duplicate_rows.append(idx)
            else:
                seen[parsed.fingerprint] = parsed
            result.rows.append(parsed)
    except csv.Error:
        result.errors.append(RowError(reader.line_num, "file", "Некорректное экранирование CSV"))
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

    if m.direction:
        raw_dir = row[m.direction].strip().casefold()
        if raw_dir in {value.casefold() for value in m.direction_in_values}:
            direction = Direction.IN
        elif raw_dir in {"out", "debit", "расход", "списание", "-"}:
            direction = Direction.OUT
        else:
            raise ValueError("неизвестное или пустое направление операции")

    if amount_minor < 0:
        raise ValueError("отрицательный модуль суммы")

    for key in (m.external_id, m.counterparty_ref):
        value = row.get(key) or "" if key else ""
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
            raise ValueError("идентификатор содержит управляющий символ")
    external_id = (row.get(m.external_id) or "").strip() or None if m.external_id else None
    currency = ((row.get(m.currency) or "").strip() or m.default_currency) if m.currency else m.default_currency
    counterparty_name = (row.get(m.counterparty_name) or "").strip() or None if m.counterparty_name else None
    counterparty_ref = (row.get(m.counterparty_ref) or "").strip() or None if m.counterparty_ref else None
    purpose = (row.get(m.purpose) or "").strip() or None if m.purpose else None
    if currency != "RUB":
        raise ValueError("поддерживается только валюта RUB")
    for value, maximum in ((counterparty_name, 500), (counterparty_ref, 200), (external_id, 200)):
        if value is not None and len(value) > maximum:
            raise ValueError("текстовое поле превышает допустимую длину")
    balance_minor = _signed_amount(row[m.balance]) if m.balance and row.get(m.balance) else None

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
    return _parse_amount_minor(value)

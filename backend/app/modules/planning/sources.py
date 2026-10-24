"""Чистый csv-obligations-v1 adapter; даты/суммы берутся только из источника."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date

from app.modules.contracts import Direction, PlannedEventDTO

MAX_CONTENT_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10_000
MAX_SOURCE_AMOUNT_MINOR = 9_000_000_000_000_000
REQUIRED_COLUMNS = (
    "id",
    "counterparty_ref",
    "direction",
    "amount",
    "currency",
    "due_date",
    "available_at",
    "kind",
    "provenance",
)


@dataclass(frozen=True)
class ObligationRowError:
    row: int
    field: str
    code: str


@dataclass(frozen=True)
class ObligationImportItem:
    event: PlannedEventDTO
    source_ref: str
    currency: str
    provenance: str
    tax_regime: str | None


@dataclass(frozen=True)
class ObligationParseResult:
    items: list[ObligationImportItem]
    errors: list[ObligationRowError]
    content_sha256: str


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)


def parse_obligations_csv(content: str, *, as_of: date, source_name: str) -> ObligationParseResult:
    """Невалидные строки дают ошибки без исходных значений; caller запрещает partial commit."""
    errors, items = [], []
    if not isinstance(content, str):
        return ObligationParseResult([], [ObligationRowError(0, "content", "invalid_content_type")], "")
    # Быстрая граница до UTF8 encode; затем ограничение именно байтов, не символов.
    if len(content) > MAX_CONTENT_BYTES:
        return ObligationParseResult([], [ObligationRowError(0, "content", "content_too_large")], "")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        return ObligationParseResult([], [ObligationRowError(0, "content", "invalid_text_encoding")], "")
    if len(encoded) > MAX_CONTENT_BYTES:
        return ObligationParseResult([], [ObligationRowError(0, "content", "content_too_large")], "")
    digest = hashlib.sha256(encoded).hexdigest()
    if type(as_of) is not date:
        errors.append(ObligationRowError(0, "as_of", "invalid_date"))
    if (
        not isinstance(source_name, str)
        or not source_name.strip()
        or len(source_name) > 160
        or _has_control(source_name)
    ):
        errors.append(ObligationRowError(0, "source_name", "invalid_source_name"))
    if errors:
        return ObligationParseResult([], errors, digest)
    source_name = source_name.strip()
    reader = csv.reader(io.StringIO(content.removeprefix("\ufeff"), newline=""), delimiter=";", strict=True)
    seen, row_count = set(), 0
    try:
        header = next(reader, None)
        if not header:
            return ObligationParseResult([], [ObligationRowError(1, "header", "missing_header")], digest)
        if any(_has_control(value) for value in header):
            return ObligationParseResult([], [ObligationRowError(1, "header", "invalid_control_characters")], digest)
        header = [value.strip() for value in header]
        if len(set(header)) != len(header):
            errors.append(ObligationRowError(1, "header", "duplicate_columns"))
        if not set(REQUIRED_COLUMNS).issubset(header):
            errors.append(ObligationRowError(1, "header", "missing_columns"))
        if set(header) - {*REQUIRED_COLUMNS, "tax_regime"}:
            errors.append(ObligationRowError(1, "header", "unknown_columns"))
        if errors:
            return ObligationParseResult([], errors, digest)
        for cells in reader:
            row_count += 1
            row = reader.line_num
            if row_count > MAX_ROWS:
                errors.append(ObligationRowError(row, "row", "too_many_rows"))
                break
            if len(cells) != len(header):
                errors.append(ObligationRowError(row, "row", "wrong_column_count"))
                continue
            before = len(errors)
            for field, value in zip(header, cells, strict=True):
                if len(value) > 1000 or _has_control(value):
                    errors.append(ObligationRowError(row, field, "invalid_text_length_or_control"))
            if len(errors) != before:
                continue
            values = {key: value.strip() for key, value in zip(header, cells, strict=True)}
            external_id = values["id"]
            source_ref = f"{source_name}:{external_id}"
            if not external_id or ":" in external_id or len(external_id) > 128 or len(source_ref) > 200:
                errors.append(ObligationRowError(row, "id", "invalid_source_id"))
            elif external_id in seen:
                errors.append(ObligationRowError(row, "id", "duplicate_source_id"))
            seen.add(external_id)
            if not values["counterparty_ref"] or len(values["counterparty_ref"]) > 256:
                errors.append(ObligationRowError(row, "counterparty_ref", "invalid_counterparty_ref"))
            if values["direction"] not in {"in", "out"}:
                errors.append(ObligationRowError(row, "direction", "unsupported_direction"))
            amount = None
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", values["amount"]):
                errors.append(ObligationRowError(row, "amount", "invalid_decimal_amount"))
            else:
                # Целые копейки не зависят от глобального Decimal precision/rounding.
                whole, _, fraction = values["amount"].partition(".")
                amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
                if not 0 < amount <= MAX_SOURCE_AMOUNT_MINOR:
                    errors.append(ObligationRowError(row, "amount", "amount_out_of_range"))
            if values["currency"] != "RUB":
                errors.append(ObligationRowError(row, "currency", "unsupported_currency"))
            dates = {}
            for field in ("due_date", "available_at"):
                value = values[field]
                try:
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                        raise ValueError
                    dates[field] = date.fromisoformat(value)
                except ValueError:
                    errors.append(ObligationRowError(row, field, "invalid_date"))
            if dates.get("available_at", date.min) > as_of:
                errors.append(ObligationRowError(row, "available_at", "future_knowledge"))
            if values["kind"] not in {"invoice", "obligation", "tax"}:
                errors.append(ObligationRowError(row, "kind", "unsupported_kind"))
            if not values["provenance"]:
                errors.append(ObligationRowError(row, "provenance", "missing_provenance"))
            if len(errors) != before:
                continue
            event = PlannedEventDTO(
                source_ref,
                Direction(values["direction"]),
                amount,
                amount,
                dates["due_date"],
                "planned",
                values["kind"],
                "csv",
                dates["available_at"],
                counterparty_ref=values["counterparty_ref"],
            )
            items.append(
                ObligationImportItem(event, source_ref, "RUB", values["provenance"], values.get("tax_regime") or None)
            )
    except csv.Error:
        errors.append(ObligationRowError(reader.line_num or 1, "row", "malformed_csv"))
    if not row_count and not errors:
        errors.append(ObligationRowError(2, "row", "empty_data"))
    return ObligationParseResult(items, errors, digest)

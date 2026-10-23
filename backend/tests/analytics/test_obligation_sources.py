"""Согласованный CSV: provenance/даты/Decimal, без угадывания налогов и утечки строк."""

import csv
import hashlib
import io
from dataclasses import asdict
from datetime import date
from decimal import localcontext

import pytest

from app.modules.planning.sources import MAX_ROWS, parse_obligations_csv

HEADER = "id;counterparty_ref;direction;amount;currency;due_date;available_at;kind;provenance;tax_regime\n"
VALUES = ["001", "0012345678", "out", "12.34", "RUB", "2026-10-26", "2026-10-23", "tax", "DEMO synthetic source", ""]


def parse(values=None, *, content=None, source="account:demo"):
    content = HEADER + ";".join(VALUES if values is None else values) if content is None else content
    return parse_obligations_csv(content, as_of=date(2026, 10, 24), source_name=source)


def test_exact_decimal_id_provenance_and_unknown_regime():
    content = "\ufeff" + HEADER + ";".join(VALUES)
    result = parse(content=content)
    assert not result.errors and len(result.items) == 1
    item = result.items[0]
    assert item.source_ref == item.event.id == "account:demo:001"
    assert item.event.counterparty_ref == "0012345678"
    assert item.event.amount_minor == item.event.remaining_amount_minor == 1234
    assert item.event.status == "planned" and item.event.source == "csv"
    assert item.provenance == "DEMO synthetic source" and item.tax_regime is None
    assert result.content_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert parse(content=content) == result
    assert parse(content=content, source="other:demo").items[0].source_ref != item.source_ref


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("amount", "1.234", "invalid_decimal_amount"),
        ("amount", "NaN", "invalid_decimal_amount"),
        ("amount", "1e3", "invalid_decimal_amount"),
        ("amount", "0", "amount_out_of_range"),
        ("amount", "90000000000000.01", "amount_out_of_range"),
        ("currency", "USD", "unsupported_currency"),
        ("direction", "credit", "unsupported_direction"),
        ("available_at", "2026-10-25", "future_knowledge"),
        ("due_date", "2026-02-30", "invalid_date"),
        ("due_date", "20261026", "invalid_date"),
        ("provenance", "", "missing_provenance"),
        ("kind", "guess_tax", "unsupported_kind"),
        ("id", "ambiguous:id", "invalid_source_id"),
        ("counterparty_ref", "", "invalid_counterparty_ref"),
    ],
)
def test_invalid_row_errors_without_source_values(field, value, code):
    values = VALUES.copy()
    values[HEADER.strip().split(";").index(field)] = value
    result = parse(values)
    assert not result.items
    assert any(error.field == field and error.code == code and error.row == 2 for error in result.errors)
    assert all(set(asdict(error)) == {"row", "field", "code"} for error in result.errors)


def test_duplicates_headers_malformed_empty_and_resource_limits():
    row = ";".join(VALUES) + "\n"
    result = parse(content=HEADER + row * 2)
    assert len(result.items) == 1 and result.errors[0].code == "duplicate_source_id"
    assert parse(content=HEADER + row * (MAX_ROWS + 1)).errors[-1].code == "too_many_rows"
    assert parse(content="").errors[0].code == "missing_header"
    assert parse(content=HEADER).errors[0].code == "empty_data"
    assert parse(content=HEADER.replace("amount", "id") + row).errors[0].code == "duplicate_columns"
    assert parse(content=HEADER + '"unterminated').errors[0].code == "malformed_csv"
    assert parse(content="x" * (10 * 1024 * 1024 + 1)).errors[0].code == "content_too_large"
    assert parse(content=HEADER + row, source="x" * 161).errors[0].code == "invalid_source_name"


def test_mixed_rows_return_preview_but_caller_must_block_partial_commit():
    invalid = VALUES.copy()
    invalid[0], invalid[4] = "002", "USD"
    result = parse(content=HEADER + ";".join(VALUES) + "\n" + ";".join(invalid))
    assert len(result.items) == len(result.errors) == 1
    # Источник не выводится из собственной эвристики и ручная информация сохраняется.
    tax = VALUES.copy()
    tax[-1] = "SOURCE_DECLARED_REGIME"
    assert parse(tax).items[0].tax_regime == "SOURCE_DECLARED_REGIME"


def test_money_independent_of_decimal_context_and_huge_fields_rejected_before_int():
    with localcontext() as context:
        context.prec = 2
        assert parse().items[0].event.amount_minor == 1234
    values = VALUES.copy()
    values[3] = "9" * 5000
    result = parse(values)
    assert not result.items and result.errors[0].code == "invalid_text_length_or_control"


@pytest.mark.parametrize("value", ["\t001", "001\t", "\n001\n", "\x85001", "001\x7f"])
def test_raw_cell_control_characters_not_hidden_by_strip(value):
    values = VALUES.copy()
    values[0] = value
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(HEADER.strip().split(";"))
    writer.writerow(values)
    result = parse(content=stream.getvalue())
    assert not result.items and result.errors[0].code == "invalid_text_length_or_control"


@pytest.mark.parametrize("value", ["\tid", "id\t", "\nid\n"])
def test_header_control_characters_and_raw_namespace_rejected(value):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow([value, *HEADER.strip().split(";")[1:]])
    writer.writerow(VALUES)
    result = parse(content=stream.getvalue())
    assert not result.items and result.errors[0].code == "invalid_control_characters"
    assert parse(source="\taccount:demo\n").errors[0].code == "invalid_source_name"

"""Строгий разбор денег и структуры CSV без молчаливого исправления финансовых значений."""

import csv
import io

import pytest

from app.modules.imports.parser import ColumnMapping, parse_statement


def statement(amount, *, direction=None, **mapping):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    columns, values = ["date", "amount"], ["2026-01-01", amount]
    if direction is not None:
        columns.append("direction")
        values.append(direction)
        mapping["direction"] = "direction"
    writer.writerow(columns)
    writer.writerow(values)
    return parse_statement(stream.getvalue().encode(), ColumnMapping(date="date", amount="amount", **mapping))


@pytest.mark.parametrize("amount", ["1e9", "NaN123", "1.234", "1,234", "10 percent", "90000000000000.01"])
def test_invalid_amount_is_not_silently_changed(amount):
    result = statement(amount)
    assert not result.ok and not result.rows


@pytest.mark.parametrize(
    "amount,minor",
    [("1 234,56 ₽", 123456), ("1\u00a0234.56", 123456), ("(200.10)", 20010), ("90000000000000.00", 9000000000000000)],
)
def test_supported_money_is_exact(amount, minor):
    result = statement(amount)
    assert result.ok and result.rows[0].amount_minor == minor


@pytest.mark.parametrize("direction", ["mystery", ""])
def test_unknown_direction_is_error(direction):
    result = statement("100.00", direction=direction)
    assert not result.ok and not result.rows


def test_unknown_codec_becomes_preview_error():
    result = parse_statement(
        b"date,amount\n2026-01-01,100\n", ColumnMapping(date="date", amount="amount", encoding="not-a-codec")
    )
    assert not result.ok and not result.rows


@pytest.mark.parametrize(
    "content",
    [
        b"date,amount,amount\n2026-01-01,100,200\n",
        b"date,amount\n2026-01-01\n",
        b"date,amount\n2026-01-01,100,200\n",
        b'date,amount\n2026-01-01,"100\n',
    ],
)
def test_malformed_csv_is_error_not_crash(content):
    result = parse_statement(content, ColumnMapping(date="date", amount="amount"))
    assert not result.ok


def test_long_external_id_has_stable_bounded_fingerprint():
    source_id = "x" * 200
    content = f"date,amount,id\n2026-01-01,100,{source_id}\n".encode()
    mapping = ColumnMapping(date="date", amount="amount", external_id="id")
    first, second = parse_statement(content, mapping), parse_statement(content, mapping)
    assert first.ok and first.rows[0].external_id == source_id
    assert len(first.rows[0].fingerprint) <= 100
    assert first.rows[0].fingerprint == second.rows[0].fingerprint


@pytest.mark.parametrize("identifier", ["\t001", "001\u0085", "001\n"])
def test_raw_identifiers_do_not_lose_control_characters(identifier):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["date", "amount", "id"])
    writer.writerow(["2026-01-01", "100.00", identifier])
    result = parse_statement(stream.getvalue().encode(), ColumnMapping(date="date", amount="amount", external_id="id"))
    assert not result.ok and not result.rows

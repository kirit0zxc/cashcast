"""Юнит-тесты разбора CSV: деньги в копейках без float, направление, дубли, ошибки строк."""

from __future__ import annotations

from datetime import date

from app.modules.contracts import Direction
from app.modules.imports.parser import ColumnMapping, parse_statement

_SIGNED = ColumnMapping(
    date="date",
    amount="amount",
    counterparty_ref="inn",
    purpose="purpose",
    external_id="op_id",
    balance="balance",
)


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_signed_amount_to_minor_without_float() -> None:
    data = _csv(
        "date,amount,inn,purpose,op_id,balance\n"
        "2026-01-10,1234.56,7701,Оплата,op1,10000.00\n"
        "2026-01-11,-200.10,7702,Аренда,op2,9799.90\n"
    )
    result = parse_statement(data, _SIGNED)
    assert result.ok
    first, second = result.rows
    assert first.amount_minor == 123456
    assert first.direction == Direction.IN
    assert second.amount_minor == 20010
    assert second.direction == Direction.OUT
    assert first.booked_on == date(2026, 1, 10)
    assert first.balance_minor == 1000000


def test_external_id_drives_fingerprint() -> None:
    data = _csv("date,amount,inn,purpose,op_id,balance\n2026-01-10,100.00,7701,X,opX,0\n")
    result = parse_statement(data, _SIGNED)
    assert result.rows[0].fingerprint == "ext:opX"


def test_duplicate_rows_flagged_not_dropped() -> None:
    # Две одинаковые строки без внешнего ID — кандидаты в дубли, но обе сохранены.
    mapping = ColumnMapping(date="date", amount="amount", purpose="purpose")
    data = _csv("date,amount,purpose\n2026-01-10,100.00,X\n2026-01-10,100.00,X\n")
    result = parse_statement(data, mapping)
    assert len(result.rows) == 2
    assert result.duplicate_rows == [2]


def test_bad_date_reports_row_error() -> None:
    data = _csv("date,amount,purpose\nнет-даты,100.00,X\n")
    result = parse_statement(data, ColumnMapping(date="date", amount="amount", purpose="purpose"))
    assert not result.ok
    assert result.errors[0].source_row == 1


def test_missing_amount_column_reported() -> None:
    data = _csv("date,amount\n2026-01-10,100\n")
    result = parse_statement(data, ColumnMapping(date="date", amount="missing"))
    assert not result.ok


def test_separate_inflow_outflow_columns() -> None:
    # Банк отдаёт приход и расход разными колонками — направление из того, что заполнено.
    mapping = ColumnMapping(date="date", inflow="credit", outflow="debit")
    data = _csv("date,credit,debit\n2026-01-10,500.00,\n2026-01-11,,300.00\n")
    result = parse_statement(data, mapping)
    assert result.ok
    assert (result.rows[0].direction, result.rows[0].amount_minor) == (Direction.IN, 50000)
    assert (result.rows[1].direction, result.rows[1].amount_minor) == (Direction.OUT, 30000)


def test_both_inflow_and_outflow_filled_is_error() -> None:
    mapping = ColumnMapping(date="date", inflow="credit", outflow="debit")
    data = _csv("date,credit,debit\n2026-01-10,500.00,300.00\n")
    result = parse_statement(data, mapping)
    assert not result.ok


def test_direction_column_overrides_amount_sign() -> None:
    # Есть явная колонка направления: положительная сумма, но помечена как расход.
    mapping = ColumnMapping(date="date", amount="amount", direction="type")
    data = _csv("date,amount,type\n2026-01-10,500.00,расход\n2026-01-11,500.00,приход\n")
    result = parse_statement(data, mapping)
    assert result.ok
    assert result.rows[0].direction == Direction.OUT
    assert result.rows[1].direction == Direction.IN

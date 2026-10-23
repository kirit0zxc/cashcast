"""Формат организаторов: положительная сумма и русское направление операции."""

from app.modules.contracts import Direction
from app.modules.imports.parser import ColumnMapping, parse_statement


def test_participant_inflow_is_not_treated_as_expense() -> None:
    content = (
        "operation_date;amount;direction;counterparty_inn;balance_eod\n"
        "2026-09-01;123.45;Поступление;0012345678;1000.00\n"
        "2026-09-01;23.45;Списание;;1000.00\n"
    ).encode("utf-8-sig")
    result = parse_statement(
        content,
        ColumnMapping(
            date="operation_date",
            amount="amount",
            direction="direction",
            counterparty_ref="counterparty_inn",
            balance="balance_eod",
            delimiter=";",
        ),
    )
    assert result.ok
    assert [row.direction for row in result.rows] == [Direction.IN, Direction.OUT]
    assert [row.amount_minor for row in result.rows] == [12345, 2345]
    assert result.rows[0].counterparty_ref == "0012345678"

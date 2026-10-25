from datetime import date

import pytest

from app.modules.pulse.advisor.dataset import DatasetError, load_company, parse_amount_minor

HEADER = (
    "company_id;operation_id;operation_date;amount;direction;counterparty_inn;"
    "counterparty_name;payment_purpose;balance_eod\n"
)


@pytest.mark.parametrize(("raw", "minor"), [("12345.67", 1234567), ("990.00", 99000), ("0.1", 10), ("5", 500)])
def test_parse_amount_minor(raw, minor):
    assert parse_amount_minor(raw) == minor


@pytest.mark.parametrize("raw", ["много", "1.234"])
def test_parse_amount_minor_rejects(raw):
    with pytest.raises(DatasetError):
        parse_amount_minor(raw)


def _write(tmp_path, body: str):
    (tmp_path / "statements").mkdir()
    # BOM как в датасете организаторов.
    (tmp_path / "statements" / "C900.csv").write_text("﻿" + HEADER + body, encoding="utf-8")


def test_load_company_reads_dataset_format(tmp_path):
    _write(
        tmp_path,
        "C900;C900-2;2025-01-03;100.50;Поступление;0012345678;ООО «Клиент»;Оплата;1100.50\n"
        "C900;C900-1;2025-01-02;50.00;Списание;;;;1000.00\n"
        "C900;C900-1;2025-01-02;50.00;Списание;;;;1000.00\n",  # дубль строки
    )
    ops = load_company(tmp_path, "C900")
    assert [o.operation_id for o in ops] == ["C900-1", "C900-2"]
    first, second = ops
    assert first.direction == "out" and first.counterparty_inn is None and first.purpose is None
    assert second.direction == "in"
    assert second.amount_minor == 10050
    assert second.counterparty_inn == "0012345678"  # ведущие нули сохранены
    assert second.op_date == date(2025, 1, 3)
    assert second.balance_eod_minor == 110050


def test_unknown_direction_is_error(tmp_path):
    _write(tmp_path, "C900;C900-1;2025-01-02;50.00;Приход?;;;;1000.00\n")
    with pytest.raises(DatasetError, match="строка 2"):
        load_company(tmp_path, "C900")

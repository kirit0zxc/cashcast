"""Категории и календарные повторения: примеры, границы и отсутствие утечки."""

from dataclasses import replace
from datetime import date

import pytest

from app.modules.categorization.service import get_categorizer
from app.modules.contracts import Category, Direction, RecurrenceInterval, TxnDTO
from app.modules.planning.service import get_recurrence_detector


def txn(day=date(2026, 1, 31), **kwargs):
    base = TxnDTO(
        str(day), "acc", day, 10000, Direction.OUT, counterparty_ref="0012345678", purpose="Аренда", category="rent"
    )
    return replace(base, **kwargs)


@pytest.mark.parametrize(
    ("purpose", "direction", "expected"),
    [
        ("Единый налоговый платёж", Direction.OUT, Category.TAX),
        ("ЕНП", Direction.OUT, Category.TAX),
        ("Оплата за товар, в том числе НДС", Direction.OUT, Category.PURCHASES),
        ("Оплата за услуги без НДС", Direction.IN, Category.SALES),
        ("Заработная плата", Direction.OUT, Category.PAYROLL),
        ("Комиссия банка", Direction.OUT, Category.FEES),
        ("Перевод собственных средств", Direction.IN, Category.TRANSFER),
        ("Погашение кредита", Direction.OUT, Category.LOAN),
        ("Возврат оплаты за товар", Direction.IN, Category.OTHER),
        (None, Direction.OUT, Category.OTHER),
    ],
)
def test_rules(purpose, direction, expected):
    result = get_categorizer().categorize([txn(purpose=purpose, direction=direction, category=None)])
    assert result[0].category == expected
    assert result[0].reason


def test_existing_category_preserved():
    assert get_categorizer().categorize([txn(category="tax")])[0].category == Category.TAX


def test_month_end_survives_february_and_future_does_not_leak():
    dates = [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
    data = [txn(day) for day in dates]
    service = get_recurrence_detector()
    found = service.detect(data, dates[-1])
    assert len(found) == 1
    assert found[0].interval == RecurrenceInterval.MONTHLY
    assert found[0].next_expected_date == date(2026, 4, 30)
    assert service.detect([*data, txn(date(2026, 4, 1), amount_minor=999999)], dates[-1]) == found
    assert service.detect(list(reversed(data)), dates[-1]) == found


def test_weekly_and_duplicate_id():
    dates = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15)]
    data = [txn(day) for day in dates]
    found = get_recurrence_detector().detect([*data, data[0]], dates[-1])
    assert found[0].interval == RecurrenceInterval.WEEKLY
    assert found[0].typical_amount_minor == 10000
    assert len(found[0].member_transaction_ids) == 3


def test_short_stale_variable_and_mixed_accounts_not_regular():
    service = get_recurrence_detector()
    data = [txn(date(2026, month, 10)) for month in (1, 2, 3)]
    assert not service.detect(data[:2], date(2026, 3, 10))
    assert not service.detect(data, date(2026, 6, 1))
    assert not service.detect([*data[:2], replace(data[2], amount_minor=999999)], date(2026, 3, 10))
    assert not service.detect([*data[:2], replace(data[2], account_id="other")], date(2026, 3, 10))
    assert not service.detect(
        [replace(t, counterparty_ref=None, counterparty_name=None) for t in data], date(2026, 3, 10)
    )


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ([date(2026, 1, 28), date(2026, 2, 28), date(2026, 3, 28)], date(2026, 4, 28)),
        ([date(2026, 2, 28), date(2026, 3, 30), date(2026, 4, 30)], date(2026, 5, 30)),
    ],
)
def test_fixed_day_not_confused_with_month_end(days, expected):
    found = get_recurrence_detector().detect([txn(day) for day in days], days[-1])
    assert found[0].next_expected_date == expected


@pytest.mark.parametrize("purpose", ["Оплата за услуги по аккредитиву", "Оплата за товар кредитной картой"])
def test_payment_method_is_not_a_loan(purpose):
    result = get_categorizer().categorize([txn(purpose=purpose, category=None)])
    assert result[0].category == Category.PURCHASES


def test_refund_to_credit_card_is_not_sales():
    tx = txn(direction=Direction.IN, purpose="Возврат оплаты за товар на кредитную карту", category=None)
    assert get_categorizer().categorize([tx])[0].category == Category.OTHER

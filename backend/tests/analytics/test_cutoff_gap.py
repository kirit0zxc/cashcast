"""Регрессия демо: срез 01.08 видит шесть дней, а не все 90 дней CSV."""

from dataclasses import replace
from datetime import date, timedelta

from app.modules.categorization.service import get_categorizer
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, TxnDTO
from app.modules.forecasting.service import get_forecast_service
from app.modules.planning.service import get_recurrence_detector
from app.modules.pulse.frozen import FrozenPulseService


def demo(as_of=date(2026, 8, 1)):
    txns, balances = [], []
    balance = 25_000_000
    for index in range(90):
        day = date(2026, 7, 27) + timedelta(days=index)
        incoming = index % 3 != 0
        amount = (8500 + index % 5 * 500 if incoming else 12500 + index % 4 * 700) * 100
        balance += amount if incoming else -amount
        if day > as_of:
            continue
        txns.append(TxnDTO(
            f"synthetic-deploy-{index}", "demo", day, amount, Direction.IN if incoming else Direction.OUT,
            counterparty_name=f"Демо контрагент {index % 4}", counterparty_ref="0000000000",
            purpose="СИНТЕТИЧЕСКИЕ ДАННЫЕ " + ("Оплата услуг" if incoming else "Оплата поставщику"),
        ))
        balances.append(DailyBalanceDTO("demo", day, balance))
    assignments = {a.transaction_id: a.category.value for a in get_categorizer().categorize(txns)}
    txns = [replace(t, category=assignments[t.id]) for t in txns]
    return ForecastInput(
        "demo", as_of, 30, balances[-1].closing_balance_minor, 42, txns, balances, [],
        recurrences=get_recurrence_detector().detect(txns, as_of),
    )


def calculate(data):
    result = get_forecast_service().run(data)
    pulse = FrozenPulseService.build(data, result.points, result.details, company_id="demo", buffer_minor=0)
    return result, pulse


def test_august_cutoff_reproduces_screenshot_without_false_calm():
    data = demo()
    result, pulse = calculate(data)
    assert len(data.txns) == 6
    assert data.opening_balance_minor == 26_040_000
    assert result.details["quality"]["history_days"] == 6
    assert min(p.balance_p50_minor for p in result.points) == 24_790_000
    assert result.points[-1].balance_p50_minor == 28_950_000
    assert result.risk.first_negative_date is None
    assert result.risk.probability_any_negative is None
    assert pulse["cash"]["status"] == "unknown"
    assert pulse["status"] != "ok"
    assert "недостаточно" in pulse["headline"]


def test_short_history_does_not_hide_known_large_payment_gap():
    data = demo()
    payment = PlannedEventDTO(
        "large", Direction.OUT, 40_000_000, 40_000_000, date(2026, 8, 3),
        "planned", "manual", "manual", data.as_of,
    )
    result, pulse = calculate(replace(data, planned_events=[payment]))
    assert result.risk.probability_any_negative is None
    assert result.risk.first_negative_date == date(2026, 8, 3)
    assert result.risk.max_deficit_minor > 0
    assert pulse["cash"]["status"] == pulse["status"] == "risk"


def test_plan_created_after_cutoff_does_not_leak_into_historical_forecast():
    data = demo()
    future = PlannedEventDTO(
        "later", Direction.OUT, 40_000_000, 40_000_000, date(2026, 8, 3),
        "planned", "manual", "manual", date(2026, 10, 24),
    )
    expected, _ = calculate(data)
    actual, _ = calculate(replace(data, planned_events=[future]))
    assert actual.points == expected.points


def test_longer_history_restores_probability_without_inventing_gap():
    result, pulse = calculate(demo(date(2026, 10, 24)))
    assert result.details["quality"]["eligible_for_probability"]
    assert result.risk.probability_any_negative is not None
    assert result.risk.first_negative_date is None
    assert pulse["cash"]["status"] == "ok"


def test_point_quality_does_not_require_probability_quality():
    result, pulse = calculate(demo(date(2026, 9, 1)))
    assert result.details["quality"]["eligible_for_simulation"]
    assert not result.details["quality"]["eligible_for_probability"]
    assert result.risk.probability_any_negative is None
    assert pulse["cash"]["status"] == "ok"


def test_legacy_saved_result_without_quality_uses_its_frozen_input():
    data = demo()
    result, _ = calculate(data)
    details = {k: v for k, v in result.details.items() if k != "quality"}
    pulse = FrozenPulseService.build(data, result.points, details, company_id="demo", buffer_minor=0)
    assert pulse["cash"]["status"] == "unknown"

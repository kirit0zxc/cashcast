"""Защита опорной модели от подмешивания недоступных данных."""

from dataclasses import replace
from datetime import date

from app.modules.contracts import Direction, ForecastInput, PlannedEventDTO, TxnDTO
from app.modules.forecasting.baseline import BaselineForecastService


def sample() -> ForecastInput:
    return ForecastInput("acc", date(2026, 1, 1), 30, 1000, 42, [], [], [])


def test_future_and_other_account_transactions_do_not_change_baseline():
    data = sample()
    polluted = replace(
        data,
        txns=[
            TxnDTO("future", "acc", date(2026, 1, 2), 999999, Direction.IN),
            TxnDTO("other", "other", date(2026, 1, 1), 999999, Direction.IN),
        ],
    )
    assert BaselineForecastService().run(data) == BaselineForecastService().run(polluted)


def test_future_knowledge_planned_event_does_not_change_baseline():
    data = sample()
    event = PlannedEventDTO(
        "ev", Direction.OUT, 10000, 10000, date(2026, 1, 5), "planned", "invoice", "manual", date(2026, 1, 2)
    )
    assert BaselineForecastService().run(data) == BaselineForecastService().run(replace(data, planned_events=[event]))

"""Лимиты существующей модели должны срабатывать до ORM/план-факт/категоризации."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, insert, select

from app.core.models import BankTransaction, DailyBalance, ForecastRun, Job, PlannedEvent, PlannedEventMatch
from app.modules.forecasting.v2.quality import ResourceLimits
from tests.test_integration import logged_in


@pytest.fixture
def context(client, session_factory):
    return logged_in.__wrapped__(client, session_factory)


def _rows(model, count, context, today, *, future=False):
    common = {"company_id": context["company_id"], "account_id": context["account_id"]}
    for index in range(count):
        if model is BankTransaction:
            yield {**common, "booked_on": today + timedelta(days=1) if future else today,
                   "direction": "in", "amount_minor": 1, "fingerprint": f"preflight-{index}"}
        elif model is DailyBalance:
            yield {**common, "balance_date": today - timedelta(days=index), "closing_balance_minor": 0}
        else:
            yield {**common, "direction": "in", "amount_minor": 1, "remaining_amount_minor": 1,
                   "due_date": today + timedelta(days=1), "available_at": datetime.combine(
                       today + timedelta(days=1) if future else today, datetime.min.time(), UTC,
                   )}


@pytest.mark.parametrize("model,maximum", [
    (BankTransaction, ResourceLimits().transactions),
    (DailyBalance, ResourceLimits().balances),
    (PlannedEvent, ResourceLimits().events),
])
def test_oversized_account_rejected_before_matcher_and_job_creation(
    client, session_factory, context, monkeypatch, model, maximum,
):
    from app.modules.integration import plan_fact

    today = datetime.now(UTC).date()
    with session_factory() as session:
        # Настоящие legacy-строки: никакой подмены policy/COUNT-запроса моками.
        session.execute(insert(model), list(_rows(model, maximum + 1, context, today)))
        session.commit()

    class UnreachableMatcher:
        def match(self, *_args, **_kwargs):
            raise AssertionError("Слишком большой вход дошёл до сопоставления до resource guard")

    original_factory = plan_fact.get_planned_event_matcher
    monkeypatch.setattr(plan_fact, "get_planned_event_matcher", UnreachableMatcher)
    response = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": str(today), "horizon_days": 30,
    })
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "forecast_resource_limit"
    with session_factory() as session:
        for table in (Job, ForecastRun, PlannedEventMatch):
            assert session.scalar(select(func.count()).select_from(table)) == 0
    if model is DailyBalance:
        # Большая история остатков не блокирует отдельную сверку: она их не использует.
        monkeypatch.setattr(plan_fact, "get_planned_event_matcher", original_factory)
        response = client.get(f"/api/v1/companies/{context['company_id']}/plan-fact", params={
            "account_id": context["account_id"], "as_of": str(today),
        })
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("model,maximum", [
    (BankTransaction, ResourceLimits().transactions), (PlannedEvent, ResourceLimits().events),
])
def test_unknown_future_rows_do_not_consume_current_snapshot_budget(client, session_factory, context, model, maximum):
    today = datetime.now(UTC).date()
    with session_factory() as session:
        session.execute(insert(model), list(_rows(model, maximum + 1, context, today, future=True)))
        session.commit()
    response = client.post(f"/api/v1/companies/{context['company_id']}/forecasts", json={
        "account_id": context["account_id"], "as_of": str(today), "horizon_days": 30,
    })
    assert response.status_code == 202, response.text

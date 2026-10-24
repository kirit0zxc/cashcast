"""Известные факты после EOD входят в расчётный остаток, но не становятся новым EOD."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.models import BankTransaction, DailyBalance, ForecastRun, Job
from app.modules.forecasting.snapshot import build_snapshot
from app.modules.jobs.worker import run_once
from tests.test_accounts import account_context


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def _source(session_factory, context, *, balance=10000, incoming=0, outgoing=20000):
    company, _, account, other_account = context
    today = datetime.now(UTC).date()
    anchor = today - timedelta(days=1)
    common = {"company_id": uuid.UUID(company), "account_id": uuid.UUID(account)}
    with session_factory.begin() as db:
        db.add(DailyBalance(**common, balance_date=anchor, closing_balance_minor=balance, source="statement"))
        # Суммы в день EOD уже учтены. Будущие и чужого счёта нельзя подмешать.
        for index, (day, amount, direction, target) in enumerate([
            (anchor, 999, "out", account), (today, incoming, "in", account),
            (today, outgoing, "out", account), (today + timedelta(days=1), 333, "in", account),
            (today, 444, "in", other_account),
        ]):
            if amount:
                db.add(BankTransaction(company_id=uuid.UUID(company), account_id=uuid.UUID(target),
                                       booked_on=day, amount_minor=amount, direction=direction,
                                       fingerprint=f"opening-{index}"))
    return account, today, anchor


@pytest.mark.parametrize("incoming,outgoing,expected", [(0, 20000, -10000), (12345, 0, 22345), (1100, 200, 10900)])
def test_snapshot_rolls_forward_only_facts_after_anchor(session_factory, context, incoming, outgoing, expected):
    account, today, anchor = _source(session_factory, context, incoming=incoming, outgoing=outgoing)
    with session_factory() as db:
        snap = build_snapshot(db, account_id=account, as_of=today, horizon_days=1, seed=42)
        assert snap.data.opening_balance_minor == expected
        assert snap.opening_balance_minor == expected
        assert snap.data.daily_balances[-1].balance_date == anchor
        assert snap.data.daily_balances[-1].closing_balance_minor == 10000
        assert any("расчётн" in warning.lower() for warning in snap.warnings)
        assert db.scalar(select(func.count()).select_from(DailyBalance)) == 1


def test_real_worker_starts_from_observed_post_anchor_spending(client, session_factory, context):
    company = context[0]
    account, today, _ = _source(session_factory, context)
    response = client.post(f"/api/v1/companies/{company}/forecasts", json={
        "account_id": account, "as_of": today.isoformat(), "horizon_days": 1,
    })
    assert response.status_code == 202, response.text
    assert run_once(session_factory, worker_id="opening-check", lease_seconds=10)
    result = client.get(f"/api/v1/forecasts/{response.json()['forecast_run_id']}").json()
    assert result["status"] == "succeeded"
    assert result["opening_balance_minor"] == -10000
    assert result["points"][0]["balance_p50_minor"] == -10000
    assert result["risk"]["first_negative_date"] == (today + timedelta(days=1)).isoformat()


def test_roll_forward_over_money_limit_rejected_before_job(client, session_factory, context):
    account, today, _ = _source(session_factory, context, balance=9_000_000_000_000_000, incoming=1, outgoing=0)
    response = client.post(f"/api/v1/companies/{context[0]}/forecasts", json={
        "account_id": account, "as_of": today.isoformat(), "horizon_days": 1,
    })
    assert response.status_code == 422, response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(ForecastRun)) == 0

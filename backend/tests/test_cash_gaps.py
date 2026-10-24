"""Эпизоды, сохранённые источники, гипотезы и границы доступа карточки разрыва."""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.schemas.cash_gaps import CashGapPreview
from app.core.errors import AppError
from app.core.forecast_input import ForecastInputCodec
from app.core.models import CompanyMember, ForecastPoint, ForecastRun, Job, PlannedEvent
from app.modules.cash_gaps.service import CashGapService
from app.modules.contracts import DailyBalanceDTO, Direction, PlannedEventDTO
from app.modules.jobs.handlers import handle_forecast
from tests.test_accounts import account_context
from tests.test_pulse import saved_run, source

AS_OF = date(2026, 9, 30)


def build(balances, *, opening=100, planned=None, actions=None, reliable=True, observed=False):
    data = replace(
        source(empty=True),
        opening_balance_minor=opening,
        horizon_days=len(balances),
        planned_events=planned or [],
        daily_balances=[DailyBalanceDTO("account", AS_OF, opening)] if observed else [],
    )
    points = []
    previous = opening
    explanations = []
    for i, balance in enumerate(balances):
        day = AS_OF + timedelta(days=i + 1)
        known = [p for p in data.planned_events if p.due_date == day]
        incoming = sum(p.remaining_amount_minor for p in known if p.direction == Direction.IN)
        outgoing = sum(p.remaining_amount_minor for p in known if p.direction == Direction.OUT)
        residual = balance - previous - incoming + outgoing
        points.append(
            SimpleNamespace(
                point_date=day,
                balance_p50_minor=balance,
                inflow_minor=incoming + max(residual, 0),
                outflow_minor=outgoing + max(-residual, 0),
            )
        )
        for p in known:
            explanations.append(
                {
                    "kind": "planned",
                    "source_ref": p.id,
                    "label": p.kind,
                    "amount_minor": p.remaining_amount_minor,
                    "detail": {"date": day.isoformat(), "direction": p.direction.value},
                }
            )
        previous = balance
    details = {"quality": {"eligible_for_simulation": reliable, "mode": "test"}, "explanations": explanations}
    return CashGapService.build(
        data,
        points,
        details,
        company_id="company",
        preview=CashGapPreview.model_validate({"actions": actions}) if actions else None,
    )


def plan(kind="purchases", direction=Direction.OUT):
    return PlannedEventDTO(
        "p1", direction, 500, 500, date(2026, 10, 1), "planned", "manual", "manual", AS_OF, category=kind
    )


def funding(**changes):
    return {
        "kind": "financing",
        "date": "2026-10-01",
        "amount_minor": 500,
        "repayment_date": "2026-10-03",
        "cost_minor": 25,
        **changes,
    }


def test_multiple_gaps_recovery_zero_and_open_horizon():
    report = build([-50, -20, 0, -10, -5])
    first, second = report["base"]["episodes"]
    assert first["observed_days"] == 2 and first["recovery_date"] == date(2026, 10, 3)
    assert not first["duration_is_lower_bound"]
    assert second["recovery_date"] is None and second["duration_is_lower_bound"]
    assert report["base"]["max_deficit_minor"] == 50
    assert report["base"]["total_negative_days"] == 4


def test_existing_deficit_not_misreported_as_new_and_unknown_start():
    report = build([-25, 0, -10, 20], opening=-100)
    existing, new = report["base"]["episodes"]
    assert existing["kind"] == "existing" and existing["duration_is_lower_bound"]
    assert existing["observed_days"] == 2
    assert new["kind"] == "new" and report["base"]["first_new_gap_date"] == date(2026, 10, 3)
    assert report["base"]["max_deficit_minor"] == 100


def test_one_day_and_opening_recovers_immediately():
    report = build([0], opening=-100)
    assert report["base"]["episodes"][0]["recovery_date"] == date(2026, 10, 1)
    assert report["base"]["episodes"][0]["observed_days"] == 1


@pytest.mark.parametrize("reliable,status", [(True, "no_gap"), (False, "insufficient_data")])
def test_zero_is_not_a_gap_and_no_data_not_zero_risk(reliable, status):
    report = build([0, 0], opening=0, reliable=reliable)
    assert report["base"]["status"] == status
    assert report["base"]["episodes"] == []


def test_explanation_reconciles_exactly_to_minimum():
    report = build([-400, -100], planned=[plan()])
    assert sum(c["amount_minor"] for c in report["causes"]) == report["causes_balance_minor"] == -400
    cause = next(c for c in report["causes"] if c["source_ref"] == "p1")
    assert cause["evidence"] == "planned" and cause["amount_minor"] == -500


@pytest.mark.parametrize("observed", [True, False])
def test_initial_balance_evidence_distinguishes_observed_eod_from_derived(observed):
    report = build([-50], observed=observed)
    assert report["causes"][0]["evidence"] == ("observed" if observed else "estimated")


def test_delay_supplier_reappears_on_new_day_and_does_not_mutate_base():
    action = {"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True}
    report = build([-400, 100], planned=[plan()], actions=[action])
    assert [p["preview_minor"] for p in report["points"]] == [100, 100, 100]
    assert [p["base_minor"] for p in report["points"]] == [100, -400, 100]
    assert report["improvement_minor"] == 400


def test_delayed_receipt_creates_gap():
    report = build(
        [100, 100],
        opening=100,
        planned=[plan("sales", Direction.IN)],
        actions=[{"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02"}],
    )
    assert report["preview"]["max_deficit_minor"] == 400
    assert report["improvement_minor"] == -400


@pytest.mark.parametrize("kind", ["tax", "payroll", "loan", "rent", "other"])
def test_protected_payment_cannot_be_delayed(kind):
    with pytest.raises(AppError, match="недоступен"):
        build(
            [-400, 0],
            planned=[plan(kind)],
            actions=[{"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True}],
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"to_date": "2026-10-03"},
        {"to_date": "2026-10-01"},
        {"flow_id": "missing"},
        {"payment_delay_agreed": False},
    ],
)
def test_invalid_or_unagreed_delay(changes):
    action = {"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True}
    with pytest.raises(AppError):
        build([-400, 0], planned=[plan()], actions=[{**action, **changes}])


def test_duplicate_delay_is_rejected():
    action = {"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True}
    with pytest.raises(AppError):
        build([-400, 0], planned=[plan()], actions=[action, action])


def test_tax_kind_remains_protected_even_if_category_is_wrong():
    with pytest.raises(AppError):
        build(
            [-400, 0],
            planned=[replace(plan(), kind="tax")],
            actions=[{"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True}],
        )


def test_old_snapshot_without_category_is_readable_and_not_assumed_flexible():
    data = replace(source(empty=True), planned_events=[plan()])
    encoded = ForecastInputCodec.encode(data)
    encoded["input"]["planned_events"][0].pop("category")
    restored = ForecastInputCodec.decode(encoded)
    assert restored.planned_events[0].category is None
    report = build([-400, 0], planned=restored.planned_events)
    assert not report["flows"][0]["delay_allowed"]


def test_financing_repayment_and_cost_can_create_second_gap():
    report = build([-400, 100, 100], actions=[funding()])
    assert [p["preview_minor"] for p in report["points"]] == [100, 100, 600, 75]
    assert report["financing_cost_minor"] == 25 and report["debt_beyond_horizon_minor"] == 0
    report = build([-400, -200, -200], actions=[funding()])
    assert report["preview"]["first_new_gap_date"] == date(2026, 10, 3)
    assert report["preview"]["max_deficit_minor"] == 225


def test_debt_after_horizon_and_current_deficit_remains_visible():
    report = build([-100, 100], opening=-200, actions=[funding()])
    assert report["debt_beyond_horizon_minor"] == 525
    assert report["preview"]["opening_already_negative"]
    assert report["preview"]["max_deficit_minor"] == 200


@pytest.mark.parametrize("changes", [{"date": "2026-09-30"}, {"date": "2026-10-04"}, {"repayment_date": "2026-10-01"}])
def test_invalid_financing_dates(changes):
    with pytest.raises(AppError):
        build([0, 0], actions=[funding(**changes)])


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": True},
        {"amount_minor": 0},
        {"cost_minor": -1},
        {"amount_minor": 1.5},
        {"amount_minor": 9_000_000_000_000_001},
    ],
)
def test_money_contract_rejects_unsafe_input(changes):
    with pytest.raises(ValidationError):
        CashGapPreview.model_validate({"actions": [funding(**changes)]})


def test_combined_actions_and_aggregate_money_overflow():
    report = build(
        [-400, 100],
        planned=[plan()],
        actions=[
            funding(),
            {"kind": "delay", "flow_id": "known:0", "to_date": "2026-10-02", "payment_delay_agreed": True},
        ],
    )
    assert report["preview"]["max_deficit_minor"] == 0
    with pytest.raises(AppError, match="безопасный"):
        build([0, 0], actions=[funding(amount_minor=9_000_000_000_000_000)] * 2)


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def test_api_job_snapshot_access_and_no_side_effects(client, context, session_factory):
    run_id = saved_run(session_factory, context)
    path = f"/api/v1/forecasts/{run_id}"
    original = client.get(path + "/cash-gaps")
    assert original.status_code == 200, original.text
    assert original.json()["probability"] is None
    with session_factory() as session:
        before = {
            model: session.scalar(select(func.count()).select_from(model)) for model in [ForecastRun, Job, PlannedEvent]
        }
    response = client.post(path + "/cash-gap-preview", json={"actions": [funding()]})
    assert response.status_code == 200, response.text
    assert response.json()["base"] == original.json()["base"]
    assert client.get(path + "/cash-gaps").json() == original.json()
    with session_factory() as session:
        assert all(session.scalar(select(func.count()).select_from(m)) == n for m, n in before.items())
    user_id = client.get("/api/v1/auth/me").json()["id"]
    with session_factory.begin() as session:
        session.get(CompanyMember, {"company_id": uuid.UUID(context[0]), "user_id": uuid.UUID(user_id)}).role = "viewer"
    assert client.post(path + "/cash-gap-preview", json={"actions": [funding()]}).status_code == 200
    other = saved_run(session_factory, context, company=context[1])
    assert client.get(f"/api/v1/forecasts/{other}/cash-gaps").status_code == 404
    assert client.post(f"/api/v1/forecasts/{other}/cash-gap-preview", json={"actions": [funding()]}).status_code == 404
    assert (
        client.post(
            path + "/cash-gap-preview", json={"actions": [funding()]}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get(path + "/cash-gaps").status_code == 401


@pytest.mark.parametrize("missing", ["snapshot", "points", "pending"])
def test_incomplete_saved_source_is_not_silently_recomputed(client, context, session_factory, missing):
    run_id = saved_run(session_factory, context)
    with session_factory.begin() as session:
        run = session.get(ForecastRun, run_id)
        if missing == "snapshot":
            run.input_snapshot = None
        elif missing == "pending":
            run.status = "pending"
        else:
            session.query(ForecastPoint).filter(ForecastPoint.forecast_run_id == run.id).delete()
    assert client.get(f"/api/v1/forecasts/{run_id}/cash-gaps").status_code == 409


def test_real_planned_purchase_survives_snapshot_and_can_be_delayed(client, context, session_factory):
    today = date.today()
    created = client.post(
        f"/api/v1/companies/{context[0]}/planned-events",
        json={
            "account_id": context[2],
            "direction": "out",
            "amount_minor": 500,
            "due_date": (today + timedelta(days=1)).isoformat(),
            "kind": "invoice",
            "category": "purchases",
        },
    )
    assert created.status_code == 201, created.text
    queued = client.post(
        f"/api/v1/companies/{context[0]}/forecasts",
        json={
            "account_id": context[2],
            "as_of": today.isoformat(),
            "horizon_days": 30,
        },
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["forecast_run_id"]
    with session_factory.begin() as session:
        handle_forecast(session, {"forecast_run_id": run_id})
        run = session.get(ForecastRun, run_id)
        assert ForecastInputCodec.decode(run.input_snapshot).planned_events[0].category == "purchases"
    path = f"/api/v1/forecasts/{run_id}"
    card = client.get(path + "/cash-gaps").json()
    flow = next(f for f in card["flows"] if f["source_ref"] == created.json()["id"])
    assert flow["delay_allowed"]
    preview = client.post(
        path + "/cash-gap-preview",
        json={
            "actions": [
                {
                    "kind": "delay",
                    "flow_id": flow["id"],
                    "to_date": (today + timedelta(days=2)).isoformat(),
                    "payment_delay_agreed": True,
                }
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["points"][1]["delta_minor"] == 500
    assert preview.json()["points"][2]["delta_minor"] == 0

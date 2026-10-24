"""Пульс связывается с замороженным расчётом, а не с изменившейся выпиской."""

import uuid
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.api.schemas.pulse import PulseOut
from app.core.errors import AppError
from app.core.forecast_input import ForecastInputCodec
from app.core.models import CompanyMember, ForecastPoint, ForecastRun, Job
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, PlannedEventDTO, TxnDTO
from app.modules.forecasting.service import get_forecast_service
from app.modules.jobs.handlers import handle_forecast
from app.modules.pulse.advisor.baseline_curve import BaseCurve, Flow
from app.modules.pulse.advisor.rescue import PlannerConfig, _stressed, plan_rescue
from app.modules.pulse.frozen import FrozenPulseService
from app.modules.pulse.service import build_pulse
from tests.pulse_archive.leaks.test_detectors import AS_OF, card, sbp
from tests.test_accounts import account_context


def source(account="account", *, empty=False, as_of=date(2026, 9, 30)):
    txns = (
        []
        if empty
        else [
            TxnDTO(
                str(i),
                account,
                as_of - timedelta(days=40 - i),
                10000,
                Direction.IN,
                counterparty_name="Клиент",
                counterparty_ref="00123",
                purpose="Оплата по договору",
                category="sales",
            )
            for i in range(40)
        ]
    )
    balances = [] if empty else [DailyBalanceDTO(account, t.booked_on, 10000 * (i + 1)) for i, t in enumerate(txns)]
    plans = (
        []
        if empty
        else [
            PlannedEventDTO(
                "tax",
                Direction.OUT,
                9_000_000,
                9_000_000,
                as_of + timedelta(days=5),
                "planned",
                "tax",
                "manual",
                as_of,
            )
        ]
    )
    return ForecastInput(
        account, as_of, 30, 0 if empty else 400000, 42, txns, balances, plans, data_version="pulse-test"
    )


def report(data):
    result = get_forecast_service().run(data)
    pulse = FrozenPulseService.build(data, result.points, result.details, company_id="company", buffer_minor=0)
    return result, pulse


@pytest.mark.parametrize("empty", [False, True])
def test_pulse_uses_exact_saved_median_and_complete_contract(empty):
    data = source(empty=empty)
    result, pulse = report(data)
    assert pulse["cash"]["chart"]["base_minor"] == [p.balance_p50_minor for p in result.points]
    PulseOut.model_validate(
        {
            **pulse,
            "forecast_id": "run",
            "account_id": "account",
            "model_version": result.model_version,
            "data_version": data.data_version,
        }
    )
    if not empty:
        assert pulse["cash"]["first_gap_date"] == result.risk.first_negative_date.isoformat()
        assert pulse["cash"]["max_deficit_minor"] == result.risk.max_deficit_minor
        # Налог уже входит в базу: не добавляется повторно и не переносится ради улучшения.
        assert not any("поставщик" in a["title"].lower() for a in pulse["actions"])
    else:
        assert pulse["status"] == pulse["cash"]["status"] == pulse["money"]["status"] == "unknown"
        assert pulse["cash"]["plan"] is None
        assert not pulse["actions"]
        assert "зависимости от отдельных клиентов нет" not in pulse["clients"]["message"]


def test_known_negative_opening_is_risk_even_without_transactions():
    _, pulse = report(replace(source(empty=True), opening_balance_minor=-10000))
    assert pulse["cash"]["status"] == pulse["status"] == "risk"


def test_stress_uses_gross_revenue_when_net_cashflow_is_zero():
    data = source(empty=True)
    incoming = [
        TxnDTO(
            f"in{i}",
            data.account_id,
            data.as_of - timedelta(days=i),
            10000,
            Direction.IN,
            counterparty_name="Клиент",
            counterparty_ref="1234567890",
            purpose=f"Оплата по счету №{i} от {data.as_of - timedelta(days=i):%d.%m.%Y}",
            category="sales",
        )
        for i in range(90)
    ]
    outgoing = [
        replace(t, id=f"out{i}", direction=Direction.OUT, category="other", purpose="Расходы")
        for i, t in enumerate(incoming)
    ]
    data = replace(
        data,
        txns=incoming + outgoing,
        opening_balance_minor=100,
        daily_balances=[DailyBalanceDTO(data.account_id, t.booked_on, 100) for t in incoming],
    )
    result, pulse = report(data)
    curve = FrozenPulseService.curve(data, result.points, result.details, "company")
    assert curve.balances() == [p.balance_p50_minor for p in result.points]
    loss = next(s for s in pulse["clients"]["stress"] if s["kind"] == "loss")
    assert loss["creates_gap"] and loss["worst_day_shortfall_minor"] > 0
    assert min(curve.balances(_stressed(curve.flows, curve.flows, 0.2))) < 0


def test_idle_cash_includes_eod_without_transaction_and_ignores_future_eod():
    data = source(empty=True)
    txns = [
        TxnDTO(
            str(i),
            data.account_id,
            date(2026, i, 1),
            10000,
            Direction.IN,
            purpose="Оплата по договору",
            category="sales",
        )
        for i in range(1, 10)
    ]
    balances = [DailyBalanceDTO(data.account_id, t.booked_on, 100000000) for t in txns]
    data = replace(data, txns=txns, daily_balances=balances, opening_balance_minor=100000000)
    _, baseline = report(data)
    assert any(f["kind"] == "idle_cash" for f in baseline["money"]["findings"])
    low = DailyBalanceDTO(data.account_id, date(2026, 8, 15), -10000)
    _, corrected = report(replace(data, daily_balances=[*balances, low]))
    assert not any(f["kind"] == "idle_cash" for f in corrected["money"]["findings"])
    _, future = report(replace(data, daily_balances=[*balances, replace(low, balance_date=date(2026, 10, 1))]))
    assert any(f["kind"] == "idle_cash" for f in future["money"]["findings"])


def test_frozen_balance_does_not_depend_on_transaction_on_balance_day():
    data = source()
    data = replace(
        data,
        opening_balance_minor=777000,
        daily_balances=[*data.daily_balances, DailyBalanceDTO(data.account_id, data.as_of, 777000)],
    )
    result, pulse = report(data)
    assert pulse["cash"]["chart"]["base_minor"] == [p.balance_p50_minor for p in result.points]
    assert FrozenPulseService.curve(data, result.points, result.details, "company").opening_balance_minor == 777000


def test_historical_benchmark_is_not_used():
    _, pulse = report(source(as_of=date(2026, 8, 31)))
    assert any("справочник" in w and "отключено" in w for w in pulse["warnings"])


def test_short_horizon_cannot_hide_deferred_supplier_payment():
    start = date(2026, 9, 1)
    curve = BaseCurve(
        "company",
        start,
        0,
        2,
        [Flow("bill", start + timedelta(days=1), -100000, "purchase", "flexible", "Закупка", "frozen")],
    )
    plan = plan_rescue(curve, [], PlannerConfig(buffer_minor=0))
    assert not plan.variants[0].resolved
    assert not plan.variants[0].actions


def test_credit_comparison_includes_cost_and_outstanding_debt():
    start = date(2026, 9, 1)
    curve = BaseCurve(
        "company", start, 0, 30, [Flow("bill", start + timedelta(days=1), -90000, "tax", "hard", "Налог", "frozen")]
    )
    plan = plan_rescue(curve, [], PlannerConfig(buffer_minor=0))
    variant = plan.variants[-1]
    credit = variant.actions[-1]
    assert credit.cost_minor > 0
    assert variant.balances_display_minor[-1] == -90000 + credit.amount_minor - credit.cost_minor
    assert any("непогашенным" in d for d in credit.details)


@pytest.fixture
def context(client, session_factory):
    return account_context.__wrapped__(client, session_factory)


def saved_run(session_factory, context, *, company=None, empty=False):
    data = source(context[2], empty=empty)
    with session_factory.begin() as session:
        run = ForecastRun(
            company_id=uuid.UUID(company or context[0]),
            account_id=uuid.UUID(context[2]),
            as_of=data.as_of,
            horizon_days=30,
            data_version=str(uuid.uuid4()),
            model_version=get_forecast_service().model_version,
            seed=42,
            input_snapshot=ForecastInputCodec.encode(data),
        )
        session.add(run)
        session.flush()
        handle_forecast(session, {"forecast_run_id": str(run.id)})
        return str(run.id)


def test_api_frozen_source_viewer_and_company_isolation(client, context, session_factory):
    run_id = saved_run(session_factory, context)
    path = f"/api/v1/forecasts/{run_id}/pulse"
    first = client.get(path, params={"buffer_minor": 0})
    assert first.status_code == 200, first.text
    f = client.get(f"/api/v1/forecasts/{run_id}").json()
    assert first.json()["cash"]["chart"]["base_minor"] == [p["balance_p50_minor"] for p in f["points"]]
    # Новая live-запись не меняет старый пульс и не создаёт задания при чтении.
    assert (
        client.post(
            f"/api/v1/companies/{context[0]}/planned-events",
            json={
                "account_id": context[2],
                "due_date": "2026-10-30",
                "direction": "out",
                "amount_minor": 123456,
            },
        ).status_code
        == 201
    )
    user_id = client.get("/api/v1/auth/me").json()["id"]
    with session_factory.begin() as session:
        session.get(CompanyMember, {"company_id": uuid.UUID(context[0]), "user_id": uuid.UUID(user_id)}).role = "viewer"
    assert client.get(path, params={"buffer_minor": 0}).json() == first.json()
    other = saved_run(session_factory, context, company=context[1])
    assert client.get(f"/api/v1/forecasts/{other}/pulse").status_code == 404
    assert client.get(f"/api/v1/forecasts/{uuid.uuid4()}/pulse").status_code == 404
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
    client.cookies.clear()
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("buffer", ["-1", "abc", "1.5", "9000000000000001"])
def test_api_rejects_invalid_buffer(client, context, session_factory, buffer):
    run_id = saved_run(session_factory, context, empty=True)
    assert client.get(f"/api/v1/forecasts/{run_id}/pulse", params={"buffer_minor": buffer}).status_code == 422


@pytest.mark.parametrize("missing", ["snapshot", "points", "pending"])
def test_unavailable_source_is_explicit_conflict(client, context, session_factory, missing):
    run_id = saved_run(session_factory, context)
    with session_factory.begin() as session:
        run = session.get(ForecastRun, run_id)
        if missing == "snapshot":
            run.input_snapshot = None
        elif missing == "pending":
            run.status = "pending"
        else:
            session.query(ForecastPoint).filter(ForecastPoint.forecast_run_id == run.id).delete()
    assert client.get(f"/api/v1/forecasts/{run_id}/pulse").status_code == 409


def test_money_limit_is_explicit():
    with pytest.raises(AppError, match="безопасный"):
        FrozenPulseService.check_numbers({"amount_minor": 9_000_000_000_000_001})


def test_overlapping_savings_are_not_promised_as_combined_return():
    # Оба варианта относятся к одному карточному обороту и имеют общую базу.
    ops = [card(date(2026, 3, 2), "1000000-00", "25000-00"), sbp(date(2026, 3, 3), "100000-00", "400-00")]
    pulse = build_pulse(ops, "C900", AS_OF).to_dict()
    kinds = {f["kind"] for f in pulse["money"]["findings"]}
    assert {"card_rate_above_peers", "sbp_shift"} <= kinds
    assert "Можно вернуть" not in pulse["headline"]
    assert any("не складывайте" in w for w in pulse["money"]["warnings"])

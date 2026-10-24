"""План спасения на вручную собранных кривых: каждое правило — на маленьком примере."""

from datetime import date, timedelta

from app.modules.pulse.advisor.baseline_curve import BaseCurve, Flow, build_base_curve
from app.modules.pulse.advisor.dataset import Operation
from app.modules.pulse.advisor.rescue import PlannerConfig, auto_buffer, plan_rescue, supplier_tolerance_days

AS_OF = date(2026, 3, 31)  # вторник
ZERO_BUFFER = PlannerConfig(buffer_minor=0)


def rub(x: int) -> int:
    return x * 100


def flow(ref: str, day: date, amount_rub: int, flex: str, kind: str = "x") -> Flow:
    return Flow(ref, day, rub(amount_rub), kind, flex, ref, "test")


def curve(opening_rub: int, *flows: Flow) -> BaseCurve:
    return BaseCurve("C900", AS_OF, rub(opening_rub), 45, list(flows))


def test_no_rescue_when_balance_stays_above_buffer():
    c = curve(1_000_000, flow("pay", date(2026, 4, 10), -100_000, "hard", "payroll"))
    plan = plan_rescue(c, [], ZERO_BUFFER)
    assert not plan.needs_rescue and plan.variants == []
    assert plan.base["first_gap_date"] is None


def test_owner_withdrawal_is_postponed_and_hard_payment_is_not_moved():
    c = curve(
        200_000,
        flow("owner", date(2026, 4, 6), -150_000, "owner", "owner_withdrawal"),
        flow("pay", date(2026, 4, 10), -100_000, "hard", "payroll"),
        flow("in", date(2026, 4, 20), 300_000, "inflow", "revenue"),
    )
    plan = plan_rescue(c, [], ZERO_BUFFER)
    assert plan.needs_rescue and plan.base["first_gap_date"] == date(2026, 4, 10)
    (variant,) = plan.variants  # без кредита хватило — второго варианта нет
    assert variant.resolved and variant.total_cost_minor == 0
    (action,) = variant.actions
    assert action.kind == "postpone_owner"
    assert action.to_date == date(2026, 4, 20)  # первый рабочий день после ямы
    assert action.amount_minor == rub(150_000)
    assert variant.min_balance_minor == rub(100_000)


def test_supplier_payment_deferred_until_money_arrives():
    c = curve(
        100_000,
        flow("sup", date(2026, 4, 6), -80_000, "flexible", "purchases"),
        flow("pay", date(2026, 4, 7), -50_000, "hard", "payroll"),
        flow("in", date(2026, 4, 13), 200_000, "inflow", "revenue"),
    )
    plan = plan_rescue(c, [], ZERO_BUFFER)
    (variant,) = plan.variants
    (action,) = variant.actions
    assert action.kind == "defer_suppliers" and variant.resolved
    assert action.to_date == date(2026, 4, 13)


def test_supplier_deferral_is_limited_and_credit_covers_the_rest():
    c = curve(
        100_000,
        flow("sup", date(2026, 4, 6), -80_000, "flexible", "purchases"),
        flow("pay", date(2026, 4, 7), -50_000, "hard", "payroll"),
        flow("in", date(2026, 5, 4), 200_000, "inflow", "revenue"),
    )
    plan = plan_rescue(c, [], ZERO_BUFFER)
    no_credit, with_credit = plan.variants
    assert not no_credit.resolved and with_credit.resolved
    defer = no_credit.actions[0]
    assert defer.to_date == date(2026, 4, 20)  # не дальше 14 дн. по умолчанию
    assert [a.kind for a in with_credit.actions] == ["defer_suppliers", "credit"]


def test_credit_amount_term_and_integer_cost():
    c = curve(
        50_000,
        flow("pay", date(2026, 4, 10), -100_000, "hard", "payroll"),
        flow("in", date(2026, 4, 20), 200_000, "inflow", "revenue"),
    )
    plan = plan_rescue(c, [], ZERO_BUFFER)
    no_credit, with_credit = plan.variants
    assert no_credit.actions == [] and not no_credit.resolved
    (credit,) = with_credit.actions
    assert credit.amount_minor == rub(50_000)
    assert (credit.from_date, credit.to_date) == (date(2026, 4, 10), date(2026, 4, 20))
    # 50 000 ₽ × 20% × 10 дн. / 365 = 273.97 ₽, целые копейки с округлением вниз.
    # Интеграция округляет стоимость вверх до копейки и включает её в график.
    assert credit.cost_minor == 27_398
    assert with_credit.min_balance_minor == 0


def test_buffer_auto_and_user_override():
    c = curve(1_000_000, flow("pay", date(2026, 4, 10), -100_000, "hard", "payroll"))
    assert auto_buffer(c, 0.5) == int(rub(100_000) * 7 / 45 * 0.5)
    auto = plan_rescue(c, [])
    assert auto.buffer_source == "auto" and auto.buffer_minor == auto_buffer(c, 0.5)
    user = plan_rescue(c, [], PlannerConfig(buffer_minor=rub(950_000)))
    assert user.buffer_source == "user" and user.needs_rescue  # 900 тыс. < 950 тыс.


def test_stress_check_with_lower_inflows():
    c = curve(
        0,
        flow("in1", date(2026, 4, 2), 100_000, "inflow", "revenue"),
        flow("owner", date(2026, 4, 3), -50_000, "owner", "owner_withdrawal"),
        flow("pay", date(2026, 4, 6), -90_000, "hard", "payroll"),
        flow("in2", date(2026, 4, 13), 100_000, "inflow", "revenue"),
    )
    (variant,) = plan_rescue(c, [], ZERO_BUFFER).variants
    assert variant.resolved
    # При поступлениях −20%: 80 000 − 90 000 = −10 000 ₽ к 06.04.
    assert not variant.stress_holds
    assert variant.stress_min_balance_minor == rub(-10_000)


def test_structural_shortfall_is_flagged():
    day = AS_OF + timedelta(days=1)
    flows = []
    while day <= AS_OF + timedelta(days=45):
        if day.weekday() < 5:
            flows.append(flow(f"rent{day}", day, -5_000, "hard", "rent"))
        day += timedelta(days=1)
    plan = plan_rescue(curve(100_000, *flows), [], ZERO_BUFFER)
    assert plan.structural_shortfall
    assert any("структурную нехватку" in w for w in plan.warnings)


def test_plan_is_json_ready():
    c = curve(
        50_000,
        flow("pay", date(2026, 4, 10), -100_000, "hard", "payroll"),
        flow("in", date(2026, 4, 20), 200_000, "inflow", "revenue"),
    )
    data = plan_rescue(c, [], ZERO_BUFFER).to_dict()
    assert data["days_display"][0] == "2026-04-01" and len(data["days_display"]) == 30
    assert data["variants"][1]["actions"][0]["to_date"] == "2026-04-20"
    assert isinstance(data["variants"][1]["actions"][0]["cost_minor"], int)


_n = 0


def op(
    day: date, rub_amount: int, direction: str, purpose: str, balance_rub: int | None = None, name: str = "ООО «Х»"
) -> Operation:
    global _n
    _n += 1
    return Operation(
        "C900",
        f"o{_n}",
        day,
        rub(rub_amount),
        direction,  # type: ignore[arg-type]
        None,
        name,
        purpose,
        rub(balance_rub) if balance_rub is not None else None,
    )


def test_supplier_tolerance_from_own_history():
    ops = [
        op(
            date(2026, 3, 1) + timedelta(days=i),
            1_000,
            "out",
            f"Оплата по УПД № {i} от {(date(2026, 3, 1) + timedelta(days=i - lag)):%d.%m.%Y} "
            "за товар по договору поставки",
        )
        for i, lag in enumerate([5] * 8 + [20, 20])
    ]
    days, note = supplier_tolerance_days(ops, AS_OF, PlannerConfig())
    assert days == 15  # p90 20 − медиана 5
    assert "5 дн." in note
    assert supplier_tolerance_days([], AS_OF, PlannerConfig())[0] == 14


def test_base_curve_from_operations():
    ops = []
    monday = date(2026, 2, 2)
    for w in range(8):
        ops.append(
            op(monday + timedelta(weeks=w), 70_000, "in", "Оплата по УПД № 1 от 01.01.2026", balance_rub=500_000)
        )
    ops.append(
        op(
            date(2026, 3, 20),
            500_000,
            "in",
            "Предоставление беспроцентного займа учредителем по договору № 1/2",
            balance_rub=1_000_000,
        )
    )
    for m in (1, 2, 3):
        ops.append(
            op(date(2026, m, 15), 30_000, "out", "Перевод собственных средств на личную карту", balance_rub=970_000)
        )
    ops.sort(key=lambda o: o.op_date)
    c = build_base_curve(ops, "C900", AS_OF)
    # Остаток последней операции до среза — понедельник 23.03.
    assert c.opening_balance_minor == rub(500_000)
    inflows = [f for f in c.flows if f.flexibility == "inflow"]
    assert inflows and all(f.day.weekday() == 0 for f in inflows)  # только понедельники
    # 7 оплат на 8 понедельников окна (02.02 вне окна, 30.03 оплаты не было);
    # заём учредителя в поступления не входит.
    assert all(f.amount_minor == rub(70_000) * 7 // 8 for f in inflows)
    owner = [f for f in c.flows if f.flexibility == "owner"]
    # Горизонт 45 дн. от 31.03 заканчивается 15.05 включительно.
    assert [f.day for f in owner] == [date(2026, 4, 15), date(2026, 5, 15)]
    assert owner[0].amount_minor == -(rub(90_000) * 30 // 182)
    assert not any(f.kind == "loan" for f in c.flows)

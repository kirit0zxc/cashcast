"""Стресс-тест по клиентам на выдуманной компании: один B2B-клиент и эквайринг."""

from datetime import date, timedelta

from app.modules.pulse.advisor.baseline_curve import BaseCurve, Flow
from app.modules.pulse.advisor.client_stress import _apply, describe, stress_clients
from app.modules.pulse.advisor.dataset import Operation

AS_OF = date(2026, 3, 31)
_n = 0


def rub(x: int) -> int:
    return x * 100


def op(day: date, amount: int, purpose: str, inn: str | None, name: str) -> Operation:
    global _n
    _n += 1
    return Operation("C900", f"o{_n}", day, rub(amount), "in", inn, name, purpose, None)


def history(with_client: bool = True) -> list[Operation]:
    ops = []
    for w in range(26):  # полгода, раз в неделю
        day = AS_OF - timedelta(days=7 * w + 1)
        ops.append(op(day, 100_000, "Зачисление средств по операциям эквайринга.", "0099999999", "ПАО «Банк»"))
        if with_client:
            doc = day - timedelta(days=5)
            ops.append(op(day, 100_000, f"Оплата по УПД № {w} от {doc:%d.%m.%Y}", "0011111111", "ООО «Опора»"))
    return sorted(ops, key=lambda o: o.op_date)


def curve() -> BaseCurve:
    flows = []
    d = AS_OF + timedelta(days=1)
    while d <= AS_OF + timedelta(days=45):
        if d.weekday() < 5:
            flows.append(Flow(f"in:{d}", d, rub(40_000), "revenue", "inflow", "in", "test"))
            flows.append(Flow(f"pay:{d}", d, rub(-30_000), "payroll", "hard", "pay", "test"))
        d += timedelta(days=1)
    return BaseCurve("C900", AS_OF, rub(100_000), 45, flows)


def test_apply_delay_moves_share_and_loss_removes_it():
    f = Flow("in:x", date(2026, 4, 1), rub(1_000), "revenue", "inflow", "in", "test")
    delayed = _apply([f], 0.25, "delay", 14, date(2026, 5, 15))
    assert [(x.day, x.amount_minor) for x in delayed] == [(date(2026, 4, 1), rub(750)), (date(2026, 4, 15), rub(250))]
    assert [x.amount_minor for x in _apply([f], 0.25, "loss", 0, date(2026, 5, 15))] == [rub(750)]
    # За горизонт задержанная часть выпадает.
    assert len(_apply([f], 0.25, "delay", 60, date(2026, 5, 15))) == 1


def test_stress_names_the_b2b_client_and_skips_acquiring():
    report = stress_clients(curve(), history())
    assert report.applicable and report.base_first_gap_date is None
    keys = {s.counterparty_key for s in report.scenarios}
    assert keys == {"inn:0011111111"}  # эквайринг — канал продаж, не клиент
    delay = next(s for s in report.scenarios if s.kind == "delay")
    loss = next(s for s in report.scenarios if s.kind == "loss")  # крупнейший клиент
    assert delay.share_of_inflows == 0.5
    assert delay.delay_days == 14  # задержки ровные — берём коридор кейса
    assert "сценарий кейса" in delay.basis
    # Без половины поступлений день уходит в минус: 20 000 − 30 000 ₽.
    assert loss.creates_gap and loss.first_gap_date is not None
    assert loss.worst_day_shortfall_minor > delay.worst_day_shortfall_minor > 0
    assert report.most_dangerous == "inn:0011111111"
    assert describe(loss).startswith("Если ООО «Опора» перестанет платить — разрыв")


def test_stress_not_applicable_for_retail():
    report = stress_clients(curve(), history(with_client=False))
    assert not report.applicable and report.scenarios == []
    assert "снижения выручки" in report.warnings[0]

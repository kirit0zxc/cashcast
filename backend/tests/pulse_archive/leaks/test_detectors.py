"""Каждый детектор — на маленькой выдуманной выписке."""

from datetime import date, timedelta

from app.modules.pulse.advisor.dataset import Operation
from app.modules.pulse.leaks.benchmarks import PeerStats
from app.modules.pulse.leaks.detectors import (
    Context,
    account_fee_above_peers,
    card_rate_above_peers,
    forced_collections,
    idle_cash,
    overdraft_interest,
    possible_duplicates,
    price_creep,
    sbp_shift,
    wrong_requisites,
)
from app.modules.pulse.leaks.model import LeakConfig

AS_OF = date(2026, 9, 30)
CFG = LeakConfig()
PEERS = PeerStats(
    card_rate=0.018, sbp_rate=0.005, account_fee_monthly_minor=99_000, scope="отрасль «Тест», 10 компаний"
)
_n = 0


def rub(x: float) -> int:
    return round(x * 100)


def op(
    day: date,
    amount: float,
    direction: str,
    purpose: str | None,
    *,
    inn: str | None = None,
    name: str | None = "ООО «Х»",
    balance: float | None = None,
) -> Operation:
    global _n
    _n += 1
    return Operation(
        "C900",
        f"o{_n}",
        day,
        rub(amount),
        direction,  # type: ignore[arg-type]
        inn,
        name,
        purpose,
        rub(balance) if balance is not None else None,
    )


def ctx(ops: list[Operation], peers: PeerStats | None = PEERS) -> Context:
    ops = sorted(ops, key=lambda o: o.op_date)
    start = AS_OF - timedelta(days=365)
    return Context(AS_OF, start, ops, [o for o in ops if o.op_date > start], 1.0, peers, CFG)


def card(day: date, gross: str, fee: str) -> Operation:
    return op(
        day,
        1,
        "in",
        f"Зачисление средств по операциям эквайринга. Мерчант №1. Сумма "
        f"операций {gross}, комиссия {fee}, возврат покупки 0.00.",
    )


def sbp(day: date, gross: str, fee: str) -> Operation:
    return op(
        day, 1, "in", f"Зачисление по операциям оплаты через СБП (QR-код) за 01.01.2026. Сумма {gross}, комиссия {fee}."
    )


def test_card_rate_above_peers_and_sbp_shift():
    # Карты: 1 000 000 ₽ оборота, 25 000 ₽ комиссии = 2.5% против 1.8% у похожих.
    ops = [
        card(date(2026, 3, 2), "1000000-00", "25000-00"),
        sbp(date(2026, 3, 3), "100000-00", "400-00"),
    ]  # своя СБП 0.4%
    (over,) = card_rate_above_peers(ctx(ops))
    assert over.certainty == "fact" and over.nature == "loss"
    assert over.amount_minor == rub(7_000)  # (2.5% − 1.8%) × 1 000 000
    assert "2.50%" in over.evidence[0] and "1.80%" in over.evidence[1]
    (shift,) = sbp_shift(ctx(ops))
    assert shift.certainty == "estimate" and shift.nature == "opportunity"
    assert shift.amount_minor == rub(6_300)  # (2.5% − 0.4%) × 1 000 000 × 30%
    assert "ваша ставка СБП" in shift.evidence[0]


def test_card_rate_close_to_peers_is_not_a_leak_and_peer_sbp_used():
    ops = [card(date(2026, 3, 2), "1000000-00", "18300-00")]  # 1.83% — в пределах 0.05 п.п.
    assert card_rate_above_peers(ctx(ops)) == []
    (shift,) = sbp_shift(ctx(ops))  # своей СБП нет — берём медиану похожих 0.5%
    assert "у похожих бизнесов" in shift.evidence[0]
    assert card_rate_above_peers(ctx(ops, peers=None)) == []


def test_idle_cash_uses_lowest_balance_over_year():
    ops = [op(date(2026, m, 10), 1, "out", "ЕНП", balance=500_000 + m * 1_000) for m in range(1, 10)]
    ops.append(op(date(2026, 4, 20), 1, "out", "ЕНП", balance=300_000))
    (f,) = idle_cash(ctx(ops))
    assert f.details["floor_minor"] == rub(300_000)
    assert f.details["recommended_minor"] == rub(150_000)  # половина — запас
    assert f.amount_minor == rub(18_000)  # 150 000 × 12%
    assert "20.04.2026" in f.evidence[0]


def test_idle_cash_needs_history_and_meaningful_floor():
    short = [op(date(2026, m, 10), 1, "out", "ЕНП", balance=900_000) for m in (8, 9)]
    assert idle_cash(ctx(short)) == []  # меньше полугода
    low = [op(date(2026, m, 10), 1, "out", "ЕНП", balance=50_000) for m in range(1, 10)]
    assert idle_cash(ctx(low)) == []  # меньше 100 тыс. ₽


def _rent(month_amounts: dict[tuple[int, int], float]) -> list[Operation]:
    return [
        op(
            date(y, m, 5),
            a,
            "out",
            "Оплата аренды нежилого помещения по договору № 1/2",
            inn="0012345678",
            name="ИП Арендодатель",
        )
        for (y, m), a in month_amounts.items()
    ]


def test_price_creep_compares_same_months_year_over_year():
    amounts = {(2025, m): 100_000 for m in (6, 7, 8)}
    amounts |= {(2026, m): 125_000 for m in (6, 7, 8)}
    (f,) = price_creep(ctx(_rent(amounts)))
    assert f.title == "Аренда: ИП Арендодатель — расходы +25.0% к прошлому году"
    assert f.nature == "signal" and f.period == "window"
    assert f.amount_minor == rub(75_000)  # +75 000 ₽ за квартал, без пересчёта на год
    assert f.details["growth"] == 0.25


def test_price_creep_ignores_indexation_and_gaps():
    small = {(2025, m): 100_000 for m in (6, 7, 8)} | {(2026, m): 105_000 for m in (6, 7, 8)}
    assert price_creep(ctx(_rent(small))) == []  # +5% — индексация
    gap = {(2025, m): 100_000 for m in (6, 8)} | {(2026, m): 150_000 for m in (6, 7, 8)}
    assert price_creep(ctx(_rent(gap))) == []  # июль 2025 без платежа — не регулярный


def test_possible_duplicates_skips_refunded():
    day = date(2026, 5, 12)
    purpose = "Оплата по УПД № 7 от 01.05.2026 за автозапчасти"
    dup = [op(day, 21_093.50, "out", purpose, inn="0011") for _ in range(2)]
    (f,) = possible_duplicates(ctx(dup))
    assert f.amount_minor == rub(21_093.50) and f.period == "window"
    refunded = [*dup, op(day + timedelta(days=5), 21093.5, "in", "Возврат излишне уплаченного", inn="0011")]
    assert possible_duplicates(ctx(refunded)) == []


def test_overdraft_forced_collections_and_wrong_requisites():
    ops = [
        op(date(2026, 2, 3), 1_200, "out", "Уплата процентов за пользование овердрафтом"),
        op(date(2026, 3, 3), 800, "out", "Уплата процентов по договору кредитной линии"),
        op(date(2026, 4, 1), 50_000, "out", "Списание по исполнительному листу ФС № 1"),
        op(date(2026, 4, 2), 3_000, "out", "Списание по поручению налогового органа № 5"),
        op(date(2026, 6, 1), 40_000, "out", "Оплата по счету № 1 от 30.05.2026"),
        op(
            date(2026, 6, 6), 40_000, "in", "Возврат платежа: неверно указаны реквизиты получателя. Оплата по счету № 1"
        ),
    ]
    c = ctx(ops)
    (od,) = overdraft_interest(c)
    assert od.amount_minor == rub(2_000)
    (fc,) = forced_collections(c)
    assert fc.amount_minor == rub(53_000) and fc.details == {"court": 1, "tax": 1}
    (wr,) = wrong_requisites(c)
    assert wr.nature == "frozen" and wr.details["avg_days_frozen"] == 5.0


def test_account_fee_above_peers_uses_monthly_median():
    ops = [op(date(2026, m, 1), 1_490, "out", "Комиссия за ведение счета за месяц") for m in range(1, 7)]
    (f,) = account_fee_above_peers(ctx(ops))
    assert f.amount_minor == rub((1_490 - 990) * 12)
    cheap = [op(date(2026, m, 1), 1_000, "out", "Комиссия за ведение счета") for m in range(1, 7)]
    assert account_fee_above_peers(ctx(cheap)) == []  # +1% к медиане — не переплата


def test_wrong_requisites_pairs_with_original_not_repayment():
    ops = [
        op(date(2026, 8, 28), 168_813.91, "out", "Оплата по УПД № 2070 от 16.08.2026"),
        op(
            date(2026, 8, 31),
            168_813.91,
            "in",
            "Возврат платежа: неверно указаны реквизиты получателя. Оплата по УПД № 2070",
        ),
        op(date(2026, 8, 31), 168_813.91, "out", "Оплата по УПД № 2070 от 16.08.2026"),
    ]
    (wr,) = wrong_requisites(ctx(ops))
    assert wr.details["avg_days_frozen"] == 3.0  # 28.08 -> 31.08, а не 0 дней

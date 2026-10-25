"""Рейтинг на маленьких выдуманных историях: каждая проверяет одно правило."""

from datetime import date, timedelta

from app.modules.pulse.advisor.counterparties import RatingConfig, rate_counterparties
from app.modules.pulse.advisor.dataset import Operation

AS_OF = date(2026, 6, 30)
START = date(2025, 7, 1)

_counter = 0


def op(
    day: date,
    amount_rub: int,
    purpose: str | None,
    inn: str | None = "0011111111",
    name: str = "ООО «Клиент»",
    direction: str = "in",
) -> Operation:
    global _counter
    _counter += 1
    return Operation(
        company_id="C900",
        operation_id=f"C900-{_counter}",
        op_date=day,
        amount_minor=amount_rub * 100,
        direction=direction,  # type: ignore[arg-type]
        counterparty_inn=inn,
        counterparty_name=name,
        purpose=purpose,
        balance_eod_minor=None,
    )


def client_payments(
    inn: str,
    lags: list[int],
    *,
    every_days: int = 14,
    start: date = START,
    amount: int = 10_000,
    partial_every: int = 0,
) -> list[Operation]:
    """Оплаты клиента раз в every_days, каждая через lag дней после своего УПД."""
    ops = []
    for i, lag in enumerate(lags):
        paid = start + timedelta(days=i * every_days)
        doc = paid - timedelta(days=lag)
        prefix = "Частичная оплата" if partial_every and i % partial_every == 0 else "Оплата"
        ops.append(
            op(paid, amount, f"{prefix} по УПД № {i + 1} от {doc:%d.%m.%Y}. Без НДС", inn=inn, name=f"ООО «{inn}»")
        )
    return ops


def by_inn(report, inn):
    return next(c for c in report.clients if c.counterparty_inn == inn)


def test_reliable_and_slow_but_stable():
    ops = client_payments("0000000001", [3] * 25) + client_payments("0000000002", [45] * 25)
    report = rate_counterparties(ops, "C900", AS_OF)
    assert report.applicable
    assert by_inn(report, "0000000001").grade == "A"
    slow = by_inn(report, "0000000002")
    assert slow.grade == "B"
    assert slow.lag_days_median == 45.0
    assert "45 дн." in slow.reasons[0]


def test_drift_to_slower_payments_is_c():
    ops = client_payments("0000000003", [10] * 21 + [30] * 4)
    rating = by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000003")
    assert rating.grade == "C"
    assert rating.lag_drift_days == 20.0
    assert any("медленнее обычного на 20 дн." in r for r in rating.reasons)


def test_unstable_lags_is_c():
    ops = client_payments("0000000004", [5, 60] * 12)
    assert by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000004").grade == "C"


def test_frequent_partial_payments_is_c():
    ops = client_payments("0000000005", [5] * 24, partial_every=2)
    rating = by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000005")
    assert rating.grade == "C"
    assert rating.partial_share == 0.5


def test_long_silence_is_d():
    # Платил каждые 14 дней, последняя оплата за 100 дней до среза.
    ops = client_payments("0000000006", [5] * 20, start=AS_OF - timedelta(days=100 + 19 * 14))
    rating = by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000006")
    assert rating.grade == "D"
    assert rating.days_since_last_payment == 100


def test_future_operations_are_ignored():
    ops = client_payments("0000000007", [3] * 20, start=AS_OF - timedelta(days=19 * 14))
    # После as_of клиент резко замедлился — на дату среза этого ещё не знаем.
    ops += client_payments("0000000007", [90] * 10, start=AS_OF + timedelta(days=1))
    rating = by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000007")
    assert rating.grade == "A"
    assert rating.documented_payments_count == 20


def test_revenue_share_excludes_loans_transfers_and_refunds():
    ops = client_payments("0000000008", [3] * 20, amount=10_000)  # 200 000 ₽ выручки
    ops += [
        op(AS_OF - timedelta(days=5), 500_000, "Предоставление беспроцентного займа учредителем"),
        op(AS_OF - timedelta(days=6), 300_000, "Пополнение счета собственными средствами."),
        op(
            AS_OF - timedelta(days=7),
            50_000,
            "Возврат платежа: неверно указаны реквизиты получателя. Оплата по УПД № 1 от 01.06.2026",
        ),
        op(AS_OF - timedelta(days=8), 200_000, "Зачисление по операциям эквайринга.", inn=None, name="ПАО «Банк»"),
    ]
    report = rate_counterparties(ops, "C900", AS_OF)
    rating = by_inn(report, "0000000008")
    assert rating.received_minor == 20_000_000
    assert rating.revenue_share == 0.5  # 200 тыс. из 400 тыс. операционной выручки
    assert report.summary["excluded_non_operating"] == {"loan": 1, "own_transfer": 1, "refund": 1}
    assert any("Крупный клиент: 50%" in r for r in rating.reasons)


def test_prepayments_and_too_few_documents_are_not_rated():
    ops = client_payments("0000000009", [3] * 4)  # меньше min_documented_payments
    ops += [
        op(START + timedelta(days=i), 1000, "Предоплата по счету № 1 от 01.01.2026", inn="0000000010")
        for i in range(10)
    ]
    report = rate_counterparties(ops, "C900", AS_OF)
    assert not report.applicable
    assert report.summary["skipped_few_documented_payments"] == 2
    assert "неприменим" in report.warnings[-1]


def test_retail_company_without_documents_is_not_applicable():
    ops = [
        op(
            START + timedelta(days=i),
            5_000,
            "Зачисление средств по операциям эквайринга.",
            inn="0099999999",
            name="ПАО «Банк»",
        )
        for i in range(300)
    ]
    report = rate_counterparties(ops, "C900", AS_OF)
    assert not report.applicable and report.clients == []


def test_short_history_and_empty_history_warnings():
    short = client_payments("0000000011", [3] * 6, every_days=7, start=AS_OF - timedelta(days=50))
    assert any("История короче" in w for w in rate_counterparties(short, "C900", AS_OF).warnings)
    empty = rate_counterparties([], "C900", AS_OF)
    assert not empty.applicable and "Нет операций" in empty.warnings[0]


def test_clients_sorted_by_attention_and_json_ready():
    ops = client_payments("0000000001", [3] * 25) + client_payments("0000000003", [10] * 21 + [30] * 4)
    report = rate_counterparties(ops, "C900", AS_OF, RatingConfig())
    assert [c.grade for c in report.clients] == ["C", "A"]
    data = report.to_dict()
    assert data["as_of"] == "2026-06-30"
    assert isinstance(data["clients"][0]["received_minor"], int)
    assert data["clients"][0]["last_payment_date"].startswith("2026-")


def _ending(inn: str, days_before: int, count: int = 20, amount: int = 10_000, every_days: int = 14) -> list[Operation]:
    """Ровный ритм раз в every_days; последняя оплата за days_before дней до среза."""
    start = AS_OF - timedelta(days=days_before + (count - 1) * every_days)
    return client_payments(inn, [5] * count, every_days=every_days, start=start, amount=amount)


def test_early_warning_silence_vs_rhythm():
    # Обычный перерыв 14 дн., молчит 25 дн. (≥ 1.5×14) — до D ещё далеко.
    rating = by_inn(rate_counterparties(_ending("0000000030", 25), "C900", AS_OF), "0000000030")
    assert rating.grade == "A"  # оценку ранний сигнал не меняет
    assert rating.early_warning is not None
    assert rating.early_warning.rules == ["silence_vs_rhythm"]
    assert "Не платит 25 дн. — обычно перерыв не дольше 14 дн." in rating.early_warning.reasons


def test_early_warning_volume_drop():
    # 20 оплат по 10 000 ₽, затем 6 последних по 2 000 ₽; молчит 15 дн. (≥14, но < 21).
    ops = _ending("0000000031", 15 + 6 * 14, count=20) + _ending("0000000031", 15, count=6, amount=2_000)
    rating = by_inn(rate_counterparties(ops, "C900", AS_OF), "0000000031")
    assert rating.early_warning is not None
    assert rating.early_warning.rules == ["volume_drop"]
    assert "заплатил на 80% меньше" in rating.early_warning.reasons[0]


def test_no_early_warning_for_regular_or_d_or_unknown_rhythm():
    regular = rate_counterparties(_ending("0000000032", 5), "C900", AS_OF)
    assert by_inn(regular, "0000000032").early_warning is None
    gone = by_inn(rate_counterparties(_ending("0000000033", 100), "C900", AS_OF), "0000000033")
    assert gone.grade == "D" and gone.early_warning is None  # для D уже есть сильный сигнал
    same_day = client_payments("0000000034", [5] * 6, every_days=0, start=AS_OF - timedelta(days=40))
    assert by_inn(rate_counterparties(same_day, "C900", AS_OF), "0000000034").early_warning is None


def test_early_warning_in_summary_and_json():
    report = rate_counterparties(_ending("0000000030", 25) + _ending("0000000032", 5), "C900", AS_OF)
    assert report.summary["early_warnings"] == 1
    data = report.to_dict()
    flagged = next(c for c in data["clients"] if c["early_warning"])
    assert flagged["early_warning"]["level"] == "watch"

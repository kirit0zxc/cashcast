"""Дубль строки выгрузки против настоящей двойной оплаты — различаем по остатку дня."""

from datetime import date

from app.modules.pulse.advisor.dataset import Operation
from app.modules.pulse.leaks.quality import drop_export_duplicates

D1, D2 = date(2026, 3, 9), date(2026, 3, 10)


def op(oid: str, day: date, kop: int, direction: str, balance: int) -> Operation:
    return Operation(
        "C900",
        oid,
        day,
        kop,
        direction,
        "0011",
        "ООО «Клининг»",  # type: ignore[arg-type]
        "Оплата по УПД № 1 от 01.03.2026 за уборку",
        balance,
    )


def test_export_duplicate_is_removed():
    # 100 000 − 14 268.35 = 85 731.65: остаток сходится только с одной копией.
    ops = [
        op("a", D1, 10_000_000, "in", 10_000_000),
        op("b", D2, 1_426_835, "out", 8_573_165),
        op("c", D2, 1_426_835, "out", 8_573_165),
    ]
    kept, removed = drop_export_duplicates(ops)
    assert removed == 1 and [o.operation_id for o in kept] == ["a", "b"]


def test_real_double_payment_is_kept():
    # Остаток сходится с обеими копиями: деньги действительно ушли дважды.
    ops = [
        op("a", D1, 10_000_000, "in", 10_000_000),
        op("b", D2, 2_800_000, "out", 4_400_000),
        op("c", D2, 2_800_000, "out", 4_400_000),
    ]
    kept, removed = drop_export_duplicates(ops)
    assert removed == 0 and len(kept) == 3


def test_unverifiable_first_day_is_left_alone():
    ops = [op("b", D2, 2_800_000, "out", 1_000), op("c", D2, 2_800_000, "out", 1_000)]
    assert drop_export_duplicates(ops) == (ops, 0)

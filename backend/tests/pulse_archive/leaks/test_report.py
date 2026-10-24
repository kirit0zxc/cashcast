from datetime import date

from app.modules.pulse.advisor.dataset import Operation
from app.modules.pulse.leaks.benchmarks import build_benchmarks, peer_stats
from app.modules.pulse.leaks.report import build_report

AS_OF = date(2026, 9, 30)
BENCH = {
    "overall": {"card_rate": {"median": 0.018, "companies": 50}, "sbp_rate": {"median": 0.005, "companies": 50}},
    "industries": {
        "Кафе": {"card_rate": {"median": 0.021, "companies": 12}},
        "Редкая": {"card_rate": {"median": 0.03, "companies": 2}},
    },
}
_n = 0


def op(day, kop, direction, purpose, balance=None):
    global _n
    _n += 1
    return Operation("C900", f"o{_n}", day, kop, direction, None, "ООО «Х»", purpose, balance)


def test_peer_stats_prefers_industry_with_enough_companies():
    cafe = peer_stats(BENCH, "Кафе")
    assert cafe.card_rate == 0.021 and cafe.sbp_rate == 0.005  # СБП — из общей медианы
    assert "Кафе" in cafe.scope
    rare = peer_stats(BENCH, "Редкая")  # 2 компании — мало, берём общую
    assert rare.card_rate == 0.018 and rare.scope == "все компании справочника"
    assert peer_stats(BENCH, None).card_rate == 0.018


def test_report_sorts_and_totals_and_ignores_future():
    ops = [op(date(2026, m, 10), 100, "out", "ЕНП", balance=50_000_000) for m in range(1, 10)]
    ops += [
        op(date(2026, 4, 1), 5_000_000, "out", "Списание по исполнительному листу ФС № 1"),
        op(date(2026, 10, 5), 9_999_999, "out", "Списание по исполнительному листу ФС № 2"),
    ]
    r = build_report(sorted(ops, key=lambda o: o.op_date), "C900", AS_OF, None, BENCH)
    kinds = [f.kind for f in r.findings]
    # По сумме: взыскание 50 000 ₽ раньше дохода на остатке 30 000 ₽; будущее 05.10 не видно.
    assert kinds == ["forced_collections", "idle_cash"]
    assert r.totals["opportunity_per_year_minor"] == 3_000_000  # 50% от 500 000 ₽ × 12%
    assert r.totals["one_off_loss_window_minor"] == 5_000_000
    assert any("короче года" in w for w in r.warnings)  # история с января
    data = r.to_dict()
    assert data["as_of"] == "2026-09-30" and isinstance(data["findings"][0]["amount_minor"], int)


def test_empty_report():
    r = build_report([], "C900", AS_OF, None, BENCH)
    assert r.findings == [] and r.warnings == ["Нет операций до даты анализа."]


def test_build_benchmarks_only_aggregates(tmp_path):
    (tmp_path / "statements").mkdir()
    header = (
        "company_id;operation_id;operation_date;amount;direction;counterparty_inn;"
        "counterparty_name;payment_purpose;balance_eod\n"
    )
    rows = "".join(
        f"C{i:03d};C{i:03d}-{m};2026-0{m}-05;100.00;Поступление;;Банк;Зачисление средств по "
        f"операциям эквайринга. Сумма операций 1000-00, комиссия {10 + i}-00.;1000.00\n"
        for i in (1, 2, 3)
        for m in (1, 2, 3)
    )
    for i in (1, 2, 3):
        part = "".join(line for line in rows.splitlines(keepends=True) if line.startswith(f"C{i:03d}"))
        (tmp_path / "statements" / f"C{i:03d}.csv").write_text("﻿" + header + part, encoding="utf-8")
    (tmp_path / "companies.csv").write_text("﻿company_id;industry\nC001;Кафе\nC002;Кафе\nC003;Кафе\n", encoding="utf-8")
    bench = build_benchmarks(tmp_path)
    assert bench["industries"]["Кафе"]["card_rate"] == {"median": 0.012, "companies": 3}
    assert "C001" not in str(bench)  # в справочнике нет ID компаний

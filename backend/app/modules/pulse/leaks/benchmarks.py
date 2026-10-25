# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Справочник «похожих бизнесов»: медианы по отраслям, посчитанные заранее по датасету.

Отчёт для одной компании сравнивает её только с этим небольшим JSON — так аудитор работает
на любой выписке того же формата (в том числе на контрольном датасете жюри). В файле
только агрегаты: медианы и число компаний, без строк выписок и без ID компаний.
Если в отрасли меньше min_companies значений, используется медиана по всем компаниям.

Оговорка: при отчёте по компании из того же датасета она входит в медиану своей отрасли
(одна из 7–14); на новой компании этого эффекта нет.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ..advisor.dataset import Operation, load_company
from .money import parse_commission

BENCHMARK_VERSION = "peers-0.1"
DEFAULT_PATH = Path(__file__).with_name("benchmarks.json")
MIN_COMPANIES = 3
_FIELDS = ("card_rate", "sbp_rate", "account_fee_monthly_minor")


@dataclass(frozen=True, slots=True)
class PeerStats:
    card_rate: float | None
    sbp_rate: float | None
    account_fee_monthly_minor: int | None
    scope: str  # как подписать сравнение: «отрасль: Общепит, 14 компаний»


def company_stats(ops: list[Operation], window_days: int = 365) -> dict[str, float | int]:
    """Показатели одной компании за последний год её выписки."""
    if not ops:
        return {}
    start = ops[-1].op_date - timedelta(days=window_days)
    gross: dict[str, int] = defaultdict(int)
    fee: dict[str, int] = defaultdict(int)
    acc_fee: dict[tuple[int, int], int] = defaultdict(int)
    for op in ops:
        if op.op_date <= start:
            continue
        if op.direction == "in" and (c := parse_commission(op.purpose)):
            gross[c.channel] += c.gross_minor
            fee[c.channel] += c.fee_minor
        elif op.direction == "out" and op.purpose and "ведение счета" in op.purpose.lower():
            acc_fee[(op.op_date.year, op.op_date.month)] += op.amount_minor
    out: dict[str, float | int] = {}
    if gross.get("card"):
        out["card_rate"] = fee["card"] / gross["card"]
    if gross.get("sbp"):
        out["sbp_rate"] = fee["sbp"] / gross["sbp"]
    if len(acc_fee) >= 3:
        out["account_fee_monthly_minor"] = int(statistics.median(acc_fee.values()))
    return out


def _summary(values: dict[str, list]) -> dict[str, object]:
    res: dict[str, object] = {}
    for f in _FIELDS:
        v = values.get(f, [])
        if v:
            med = statistics.median(v)
            res[f] = {"median": int(med) if f.endswith("_minor") else round(med, 5), "companies": len(v)}
    return res


def build_benchmarks(data_dir: Path) -> dict:
    industries: dict[str, str] = {}
    with (data_dir / "companies.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            industries[row["company_id"]] = row["industry"]
    by_industry: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    overall: dict[str, list] = defaultdict(list)
    for path in sorted((data_dir / "statements").glob("*.csv")):
        stats = company_stats(load_company(data_dir, path.stem))
        industry = industries.get(path.stem, "")
        for f, v in stats.items():
            by_industry[industry][f].append(v)
            overall[f].append(v)
    return {
        "version": BENCHMARK_VERSION,
        "note": "Медианы за последний год выписки по датасету участников (синтетика). Только агрегаты.",
        "overall": _summary(overall),
        "industries": {k: _summary(v) for k, v in sorted(by_industry.items()) if k},
    }


def load_benchmarks(path: Path = DEFAULT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def peer_stats(bench: dict, industry: str | None) -> PeerStats:
    """Отраслевая медиана, если в отрасли хватает компаний, иначе общая."""
    ind = bench.get("industries", {}).get(industry or "", {})
    overall = bench.get("overall", {})
    values: dict[str, object] = {}
    used_industry = False
    for f in _FIELDS:
        item = ind.get(f)
        if item and item["companies"] >= MIN_COMPANIES:
            values[f] = item["median"]
            used_industry = True
        elif overall.get(f):
            values[f] = overall[f]["median"]
    if used_industry:
        n = max(item["companies"] for item in ind.values())
        scope = f"отрасль «{industry}», {n} компаний"
    else:
        scope = "все компании справочника"
    return PeerStats(
        card_rate=values.get("card_rate"),  # type: ignore[arg-type]
        sbp_rate=values.get("sbp_rate"),  # type: ignore[arg-type]
        account_fee_monthly_minor=values.get("account_fee_monthly_minor"),  # type: ignore[arg-type]
        scope=scope,
    )

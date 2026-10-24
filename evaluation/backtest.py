"""Rolling backtest только по организаторскому ZIP. В отчёт идут агрегаты."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO  # noqa: E402
from app.modules.forecasting.baseline import BaselineForecastService  # noqa: E402
from app.modules.forecasting.seasonal import SeasonalForecastService  # noqa: E402

EXPECTED_SHA256 = "e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987"
VALIDATION = [
    date(2026, 4, 30),
    date(2026, 5, 31),
    date(2026, 6, 30),
    date(2026, 7, 31),
]
HOLDOUT = date(2026, 8, 31)
SEED = 42
HORIZON = 30


def source_fingerprints() -> dict:
    paths = [
        Path(__file__),
        *sorted(
            path
            for path in (ROOT / "backend/app/modules/forecasting").glob("*.py")
            if path.name != "snapshot.py"
        ),
        *sorted((ROOT / "backend/app/modules/planning").glob("*.py")),
        ROOT / "backend/app/modules/categorization/service.py",
        ROOT / "backend/app/modules/contracts.py",
    ]
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in paths
    }


def load_dataset(path: Path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Неизвестная версия датасета")
    transactions, balances = defaultdict(list), defaultdict(dict)
    with ZipFile(path) as archive, archive.open("all_operations.csv") as stream:
        reader = csv.DictReader(
            io.TextIOWrapper(stream, encoding="utf-8-sig"), delimiter=";"
        )
        for row in reader:
            company, day = row["company_id"], date.fromisoformat(row["operation_date"])
            direction = {"Поступление": Direction.IN, "Списание": Direction.OUT}[
                row["direction"]
            ]
            transactions[company].append(
                TxnDTO(
                    row["operation_id"],
                    company,
                    day,
                    int(Decimal(row["amount"]) * 100),
                    direction,
                    counterparty_name=row["counterparty_name"] or None,
                    counterparty_ref=row["counterparty_inn"] or None,
                    purpose=row["payment_purpose"] or None,
                )
            )
            balance = int(Decimal(row["balance_eod"]) * 100)
            if day in balances[company] and balances[company][day] != balance:
                raise ValueError("Несогласованные остатки")
            balances[company][day] = balance
    return {
        company: sorted(txns, key=lambda txn: (txn.booked_on, txn.id))
        for company, txns in transactions.items()
    }, balances


def fold(company: str, txns: list[TxnDTO], balances: dict[date, int], as_of: date):
    past_dates = sorted(day for day in balances if day <= as_of)
    if not past_dates:
        return None, "no_past_balance"
    if (as_of - past_dates[-1]).days > 3:
        return None, "stale_opening"
    end = as_of + timedelta(days=HORIZON)
    # Следующий наблюдаемый остаток подтверждает покрытие конца горизонта.
    # Это фильтр достоверности целевых значений, НЕ признак модели.
    confirming = sorted(
        day for day in balances if end <= day <= end + timedelta(days=7)
    )
    if not confirming:
        return None, "unverified_end_coverage"
    check_end = confirming[0]
    daily = defaultdict(lambda: [0, 0])
    for txn in txns:
        if as_of < txn.booked_on <= check_end:
            daily[txn.booked_on][0 if txn.direction == Direction.IN else 1] += (
                txn.amount_minor
            )
    opening = balances[past_dates[-1]]
    truth = []
    balance = opening
    for offset in range(1, (check_end - as_of).days + 1):
        day = as_of + timedelta(days=offset)
        incoming, outgoing = daily[day]
        balance += incoming - outgoing
        if day in balances and balances[day] != balance:
            return None, "unreconciled_future_target"
        if day <= end:
            truth.append((incoming, outgoing, balance))
    past = [txn for txn in txns if txn.booked_on <= as_of]
    data = ForecastInput(
        company,
        as_of,
        HORIZON,
        opening,
        SEED,
        past,
        [DailyBalanceDTO(company, day, balances[day]) for day in past_dates],
        [],
    )
    age = (as_of - min(txn.booked_on for txn in past)).days + 1
    return (data, truth, "short" if age < 90 else "established"), None


def temporal_view(transactions, balances, limit):
    """Даже quality gate validation не видит строки финального holdout."""
    return (
        {
            company: [txn for txn in txns if txn.booked_on <= limit]
            for company, txns in transactions.items()
        },
        {
            company: {day: balance for day, balance in values.items() if day <= limit}
            for company, values in balances.items()
        },
    )


class Metrics:
    def __init__(self, reference_probability=None):
        self.rows = []
        self.risks = []
        self.reference_probability = reference_probability

    def add(self, result, truth, cohort):
        if len(result.points) != len(truth):
            raise ValueError("Длина прогноза не соответствует цели")
        for index, (point, (incoming, outgoing, balance)) in enumerate(
            zip(result.points, truth, strict=True)
        ):
            self.rows.append(
                {
                    "error": point.balance_p50_minor - balance,
                    "in_error": abs(point.inflow_minor - incoming),
                    "in_actual": incoming,
                    "out_error": abs(point.outflow_minor - outgoing),
                    "out_actual": outgoing,
                    "last": index == len(truth) - 1,
                    "cohort": cohort,
                    "covered": point.balance_p10_minor
                    <= balance
                    <= point.balance_p90_minor,
                    "daily_brier": (
                        (point.probability_negative - (balance < 0)) ** 2
                        if point.probability_negative is not None
                        else None
                    ),
                }
            )
        if result.risk.probability_any_negative is not None:
            self.risks.append(
                (
                    result.risk.probability_any_negative,
                    any(balance < 0 for _, _, balance in truth),
                )
            )

    def report(self):
        if not self.rows:
            return {"days": 0, "folds": 0}
        daily_risk = [row for row in self.rows if row["daily_brier"] is not None]
        actual_in = sum(row["in_actual"] for row in self.rows)
        actual_out = sum(row["out_actual"] for row in self.rows)
        tp = sum(probability >= 0.5 and actual for probability, actual in self.risks)
        fp = sum(
            probability >= 0.5 and not actual for probability, actual in self.risks
        )
        fn = sum(probability < 0.5 and actual for probability, actual in self.risks)
        return {
            "days": len(self.rows),
            "folds": sum(row["last"] for row in self.rows),
            "balance_mae_minor": mean(abs(row["error"]) for row in self.rows),
            "balance_rmse_minor": math.sqrt(
                mean(row["error"] ** 2 for row in self.rows)
            ),
            "final_balance_mae_minor": mean(
                abs(row["error"]) for row in self.rows if row["last"]
            ),
            "inflow_wape": sum(row["in_error"] for row in self.rows) / actual_in
            if actual_in
            else None,
            "outflow_wape": sum(row["out_error"] for row in self.rows) / actual_out
            if actual_out
            else None,
            "risk_days": len(daily_risk),
            "risk_folds": len(self.risks),
            "interval_p10_p90_coverage": mean(row["covered"] for row in daily_risk)
            if daily_risk
            else None,
            "daily_negative_brier": mean(row["daily_brier"] for row in daily_risk)
            if daily_risk
            else None,
            "any_negative_brier": mean(
                (probability - actual) ** 2 for probability, actual in self.risks
            )
            if self.risks
            else None,
            "risk_reference_probability": self.reference_probability,
            "risk_reference_brier": mean(
                (self.reference_probability - actual) ** 2 for _, actual in self.risks
            )
            if self.risks and self.reference_probability is not None
            else None,
            "risk_always_zero_brier": mean(int(actual) for _, actual in self.risks)
            if self.risks
            else None,
            "any_negative_positives": sum(actual for _, actual in self.risks),
            "any_negative_precision_at_half": tp / (tp + fp) if tp + fp else None,
            "any_negative_recall_at_half": tp / (tp + fn) if tp + fn else None,
            "cohorts": {
                cohort: {
                    "days": len(rows),
                    "balance_mae_minor": mean(abs(row["error"]) for row in rows),
                }
                for cohort in ("short", "established")
                if (rows := [row for row in self.rows if row["cohort"] == cohort])
            },
        }


def evaluate(transactions, balances, cutoffs, windows, reference_probability=None):
    services = {
        "baseline": BaselineForecastService(),
        **{
            f"seasonal_w{window}": SeasonalForecastService(lookback_days=window)
            for window in windows
        },
    }
    metrics = {name: Metrics(reference_probability) for name in services}
    per_cutoff = {}
    skipped = Counter()
    hashes = {name: hashlib.sha256() for name in services}
    for as_of in cutoffs:
        current = {name: Metrics(reference_probability) for name in services}
        for company, txns in sorted(transactions.items()):
            entry, reason = fold(company, txns, balances[company], as_of)
            if entry is None:
                skipped[reason] += 1
                continue
            data, truth, cohort = entry
            for name, service in services.items():
                result = service.run(data)
                metrics[name].add(result, truth, cohort)
                current[name].add(result, truth, cohort)
                hashes[name].update(
                    json.dumps(
                        [
                            company,
                            as_of.isoformat(),
                            result.model_version,
                            [
                                [
                                    point.balance_p10_minor,
                                    point.balance_p50_minor,
                                    point.balance_p90_minor,
                                    point.probability_negative,
                                ]
                                for point in result.points
                            ],
                            result.risk.probability_any_negative,
                        ],
                        sort_keys=True,
                    ).encode()
                )
        per_cutoff[as_of.isoformat()] = {
            name: values.report() for name, values in current.items()
        }
        print(f"completed cutoff={as_of.isoformat()}", flush=True)
    return {
        "models": {name: values.report() for name, values in metrics.items()},
        "per_cutoff": per_cutoff,
        "excluded_folds": dict(sorted(skipped.items())),
        "prediction_sha256": {
            name: digest.hexdigest() for name, digest in hashes.items()
        },
    }


def run(path: Path, phase: str, config_path: Path):
    transactions, balances = load_dataset(path)
    config = None
    if phase == "holdout":
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config["selection_cutoffs"] != [cutoff.isoformat() for cutoff in VALIDATION]:
            raise ValueError("Неизвестная validation-схема")
        if (
            config["dataset_sha256"] != EXPECTED_SHA256
            or config["source_fingerprints"] != source_fingerprints()
        ):
            raise ValueError(
                "Исходники/датасет изменились после выбора модели; повторите validation"
            )
    windows = [config["lookback_days"]] if config else [28, 56, 84]
    if phase == "validation":
        transactions, balances = temporal_view(transactions, balances, HOLDOUT)
    result = evaluate(
        transactions,
        balances,
        [HOLDOUT] if config else VALIDATION,
        windows,
        config["validation_risk_prevalence"] if config else None,
    )
    if phase == "validation":
        candidates = [
            (result["models"][f"seasonal_w{window}"]["balance_mae_minor"], window)
            for window in windows
        ]
        selected = min(candidates)[1]
        chosen = result["models"][f"seasonal_w{selected}"]
        config = {
            "lookback_days": selected,
            "selection_metric": "balance_mae_minor",
            "selection_cutoffs": [cutoff.isoformat() for cutoff in VALIDATION],
            "dataset_sha256": EXPECTED_SHA256,
            "source_fingerprints": source_fingerprints(),
            "seed": SEED,
            "paths": 200,
            "validation_data_end": HOLDOUT.isoformat(),
            "validation_risk_prevalence": chosen["any_negative_positives"]
            / chosen["risk_folds"],
            "note": "Выбор среди сезонных окон по validation; baseline отдельно, без выбора на holdout.",
        }
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return {
        "phase": phase,
        "dataset_sha256": EXPECTED_SHA256,
        "seed": SEED,
        "horizon_days": HORIZON,
        "source_fingerprints": source_fingerprints(),
        "selected_lookback_days": config["lookback_days"],
        "provenance": "Синтетический датасет организаторов, all_operations.csv только один раз; не smoke.",
        "limitations": [
            "Временная проверка тех же компаний; отдельный split по новым компаниям не выполнен.",
            "Дневные цели условны при полноте выгрузки; несверенные/непокрытые цели исключены.",
            "Истинных счетов/обязательств и эталонных категорий нет; planned_events пусты.",
            "Риск проверяет наблюдаемый минус счёта с пополнениями владельца, не скрытый дефицит.",
            "Покрытие интервала и Brier измерены, калибровка вероятности не гарантируется.",
        ],
        **result,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=["validation", "holdout"])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.zip, args.phase, args.config)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                name: {
                    key: value
                    for key, value in metrics.items()
                    if key
                    in {
                        "balance_mae_minor",
                        "folds",
                        "risk_folds",
                        "any_negative_brier",
                    }
                }
                for name, metrics in result["models"].items()
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

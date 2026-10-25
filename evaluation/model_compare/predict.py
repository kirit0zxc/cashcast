"""Пример вызова сохранённых моделей на одном снимке выписки, без будущих данных.

    python -m evaluation.model_compare.predict --zip data/cashflow_dataset_participants.zip \
        --models out/models/2026-08-31 --company C001 --as-of 2026-08-31
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from . import artifacts
from .models import CURRENT, ProductModel, ensemble
from .organizers import Company, load


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--models", required=True, type=Path, help="Папка out/models/<срез>")
    parser.add_argument("--company", required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    transactions, balances = load(args.zip, {args.company})
    if args.company not in transactions:
        raise SystemExit("Компания не найдена в датасете")
    window = Company(args.company, transactions[args.company], balances[args.company]).snapshot(args.as_of)
    regressor, risk = artifacts.load(args.models)
    current = ProductModel(CURRENT).predict(window)
    lightgbm = regressor.predict(window)
    predictions = {"Текущая 2.1-w84": current, "LightGBM глобальная": lightgbm,
                   "Ансамбль 2.1 + LightGBM": ensemble(current, lightgbm)}
    probabilities = {name: float(values[0]) for name, values in risk.predict([window]).items()}
    probabilities["Текущая 2.1-w84"] = current["risk"]
    print(json.dumps({
        "company_id": args.company, "as_of": args.as_of.isoformat(), "opening_rub": window.opening / 100,
        "dates": [(args.as_of + timedelta(days=k + 1)).isoformat() for k in range(len(lightgbm["p50"]))],
        "forecast_rub": {name: {key: [float(v) / 100 for v in p[key]] for key in ("inc", "out", "p10", "p50", "p90")}
                         for name, p in predictions.items()},
        "probability_any_negative_30d": probabilities,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

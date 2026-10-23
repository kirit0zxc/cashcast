"""Проверка архива без распаковки и без публикации строк выписки."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

EXPECTED_SHA256 = "e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987"


def audit(path: Path) -> dict:
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("SHA256 архива не совпадает со спецификацией")
    with ZipFile(path) as archive:
        with archive.open("all_operations.csv") as stream:
            rows = list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"), delimiter=";"))
        statements = Counter()
        for name in sorted(archive.namelist()):
            if name.startswith("statements/") and name.endswith(".csv"):
                with archive.open(name) as stream:
                    statements.update(tuple(row.items()) for row in csv.DictReader(
                        io.TextIOWrapper(stream, encoding="utf-8-sig"), delimiter=";"
                    ))
    combined = Counter(tuple(row.items()) for row in rows)
    daily = defaultdict(lambda: {"net": 0, "balances": set()})
    keys = Counter()
    negative_companies = set()
    for row in rows:
        company, day = row["company_id"], row["operation_date"]
        amount = int(Decimal(row["amount"]) * 100)
        if row["direction"] not in {"Поступление", "Списание"} or amount < 0:
            raise ValueError("Недопустимое направление или сумма")
        balance = int(Decimal(row["balance_eod"]) * 100)
        daily[company, day]["net"] += amount if row["direction"] == "Поступление" else -amount
        daily[company, day]["balances"].add(balance)
        keys[company, row["operation_id"]] += 1
        if balance < 0:
            negative_companies.add(company)
    previous = {}
    breaks = 0
    for (company, _day), values in sorted(daily.items()):
        if len(values["balances"]) != 1:
            raise ValueError("Противоречивые остатки внутри дня")
        balance = next(iter(values["balances"]))
        if company in previous and balance - previous[company] != values["net"]:
            breaks += 1
        previous[company] = balance
    return {
        "dataset_sha256": digest,
        "rows": len(rows), "companies": len(previous),
        "first_date": min(row["operation_date"] for row in rows),
        "last_date": max(row["operation_date"] for row in rows),
        "statements_equal_combined": statements == combined,
        "duplicate_rows": sum(count - 1 for count in combined.values()),
        "duplicate_keys": sum(count - 1 for count in keys.values()),
        "missing_inn": sum(not row["counterparty_inn"] for row in rows),
        "missing_purpose": sum(not row["payment_purpose"] for row in rows),
        "negative_balance_companies": len(negative_companies),
        "balance_reconciliation_breaks": breaks,
        "note": "Аудит синтетического датасета организаторов; это не оценка точности модели.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.zip)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

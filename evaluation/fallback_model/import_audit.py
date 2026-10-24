"""Сверка парсера приложения со всеми отдельными организаторскими выписками, без БД."""

import argparse
import csv
import io
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.modules.imports.parser import ColumnMapping, parse_statement


class ImportAudit:
    @staticmethod
    def run(source, output):
        mapping = ColumnMapping(date="operation_date", amount="amount", direction="direction",
                                counterparty_name="counterparty_name", counterparty_ref="counterparty_inn",
                                purpose="payment_purpose", external_id="operation_id", balance="balance_eod", delimiter=";")
        counters = Counter()
        with ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.startswith("statements/") and name.endswith(".csv")]
            for name in names:
                content = archive.read(name)
                expected = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
                parsed = parse_statement(content, mapping)
                if parsed.errors or len(parsed.rows) != len(expected):
                    raise AssertionError("Парсер не сохранил все корректные строки организаторской выписки")
                for before, after in zip(expected, parsed.rows, strict=True):
                    direction = {"Поступление": "in", "Списание": "out"}[before["direction"]]
                    assert after.direction == direction
                    assert after.amount_minor == int(Decimal(before["amount"]) * 100)
                    assert after.balance_minor == int(Decimal(before["balance_eod"]) * 100)
                    counters[direction] += 1
                counters["rows"] += len(parsed.rows)
                counters["duplicate_rows"] += len(parsed.duplicate_rows)
        result = {"status": "passed", "files": len(names), **counters,
                  "scope": "Парсер без БД; неизвестный контрольный формат этим тестом не подтверждён"}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ImportAudit.run(args.zip, args.output)

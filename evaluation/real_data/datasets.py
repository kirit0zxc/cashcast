"""Строгая загрузка выписки и агрегированный аудит без раскрытия назначений платежей."""

import csv
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path


def minor(value: str) -> int:
    amount = Decimal(value.strip().replace(",", "") or "0") * 100
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ValueError("Некорректная сумма или более двух знаков после запятой")
    return int(amount)


@dataclass(frozen=True)
class Day:
    date: date
    incoming: int
    outgoing: int
    balance: int


class MoneyVis:
    @staticmethod
    def read(path: Path) -> tuple[list[Day], dict]:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("Пустая выписка")
        seen = set()
        records = []
        for row in reversed(rows):
            identity = row["Transaction Number"]
            if not identity or identity in seen:
                raise ValueError("Пустой или повторный ID операции")
            seen.add(identity)
            day = Day(
                datetime.strptime(row["Transaction Date"], "%d/%m/%Y").date(),
                minor(row["Credit Amount"]),
                minor(row["Debit Amount"]),
                minor(row["Balance"]),
            )
            if min(day.incoming, day.outgoing) < 0 or (day.incoming > 0) == (
                day.outgoing > 0
            ):
                raise ValueError("Неоднозначное направление операции")
            if records:
                previous = records[-1]
                if (
                    day.date < previous.date
                    or day.balance != previous.balance + day.incoming - day.outgoing
                ):
                    raise ValueError("Хронология или остатки не согласованы")
            records.append(day)
        grouped = defaultdict(list)
        for item in records:
            grouped[item.date].append(item)
        first, last = records[0].date, records[-1].date
        balance = records[0].balance - records[0].incoming + records[0].outgoing
        days = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            group = grouped[day]
            incoming, outgoing = (
                sum(r.incoming for r in group),
                sum(r.outgoing for r in group),
            )
            balance += incoming - outgoing
            days.append(Day(day, incoming, outgoing, balance))
        return days, {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(records),
            "accounts": 1,
            "calendar_days": len(days),
            "start": first.isoformat(),
            "end": last.isoformat(),
            "negative_eod_days": sum(d.balance < 0 for d in days),
            "minimum_balance_minor": min(d.balance for d in records),
            "verified_links": len(records) - 1,
            "currency": "unspecified_in_csv",
            "unit": "source_currency_minor_units",
            "calendar_assumption": "complete_statement_zero_flow_on_missing_days",
        }


class BerkaAudit:
    @staticmethod
    def read(path: Path) -> dict:
        accounts, negative_accounts, negative_days = set(), set(), set()
        types = Counter()
        negative = count = 0
        minimum = None
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter=";"):
                account, day = row["account_id"], row["date"]
                balance = minor(row["balance"])
                accounts.add(account)
                types[row["type"]] += 1
                minimum = balance if minimum is None else min(minimum, balance)
                count += 1
                if balance < 0:
                    negative += 1
                    negative_accounts.add(account)
                    negative_days.add((account, day))
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": count,
            "accounts": len(accounts),
            "negative_rows": negative,
            "negative_accounts": len(negative_accounts),
            "days_with_negative_transaction_balance": len(negative_days),
            "minimum_balance_minor": minimum,
            "types": dict(types),
            "eod_labels_verified": False,
            "limitation": "transaction_balance_is_not_verified_eod_or_independent_gap_episode",
        }

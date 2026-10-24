"""Дельта фактов: категории по ID, независимые регулярности и целые дневные суммы."""

from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date, timedelta
from statistics import mean

from app.core.forecast_input import ForecastInputCodec
from app.modules.contracts import Category, Direction, ForecastInput
from app.modules.forecasting.legacy_v1.categorization import get_categorizer, normalize
from app.modules.forecasting.legacy_v1.factories import get_recurrence_detector
from app.modules.forecasting.legacy_v1.seasonal import _recurring_history_ids
from app.modules.forecasting.v2.incremental_state import IncrementalState


class IncrementalHistory:
    @staticmethod
    def bucket(txn):
        identity = normalize(txn.counterparty_ref) or normalize(txn.counterparty_name)
        category = txn.category if txn.category in {item.value for item in Category} else None
        return (txn.account_id, txn.currency, txn.direction, identity, category or normalize(txn.purpose))

    @staticmethod
    def signature(txn):
        # Строки назначения хранятся в исходном снимке, здесь достаточно их хеша.
        return IncrementalState.digest(asdict(txn))

    @staticmethod
    def window(data):
        # Семантика frozen _history без повторной категоризации, сверка через prefix.
        observed = [t.booked_on for t in data.txns] + [b.balance_date for b in data.daily_balances]
        start = max(min(observed, default=data.as_of), data.as_of - timedelta(days=83))
        net = defaultdict(int)
        for txn in data.txns:
            net[txn.booked_on] += txn.amount_minor * (1 if txn.direction == Direction.IN else -1)
        dates = sorted(net)
        total, cursor, previous_total, previous_balance = 0, 0, 0, None
        warnings = []
        for balance in data.daily_balances:
            while cursor < len(dates) and dates[cursor] <= balance.balance_date:
                total += net[dates[cursor]]
                cursor += 1
            if previous_balance is not None and (
                balance.closing_balance_minor - previous_balance.closing_balance_minor != total - previous_total
            ):
                start = max(start, balance.balance_date + timedelta(days=1))
                warnings.append("Обнаружена несверка остатков; история до неё исключена из статистики.")
            previous_balance, previous_total = balance, total
        days = [start + timedelta(days=i) for i in range(max(0, (data.as_of - start).days + 1))]
        reliable = (
            len(days) >= 28
            and bool(data.daily_balances)
            and (data.as_of - data.daily_balances[-1].balance_date).days <= 3
            and data.daily_balances[-1].closing_balance_minor == data.opening_balance_minor
        )
        if not reliable:
            warnings.append(
                "Вероятность недоступна: короткая история, несверка или нет свежего подтверждённого остатка."
            )
        return days, list(dict.fromkeys(warnings)), reliable

    def prepare(self, data: ForecastInput, previous: dict | None):
        old = previous.get("history", {}) if previous else {}
        records = old.get("records", {})
        signatures = {txn.id: self.signature(txn) for txn in data.txns}
        changed = [txn for txn in data.txns if records.get(txn.id, {}).get("signature") != signatures[txn.id]]
        assignments = (
            {a.transaction_id: a.category.value for a in get_categorizer().categorize(changed)} if changed else {}
        )
        txns = [
            replace(txn, category=assignments[txn.id] if txn.id in assignments else records[txn.id]["category"])
            for txn in data.txns
        ]
        by_id = {txn.id: txn for txn in txns}
        buckets = defaultdict(list)
        for txn in txns:
            buckets[self.bucket(txn)].append(txn)
        old_keys = {tid: tuple(row["bucket"]) for tid, row in records.items()}
        touched = {self.bucket(by_id[t.id]) for t in changed}
        touched.update(old_keys[tid] for tid in records if tid not in by_id or tid in assignments)
        if old.get("as_of") != data.as_of.isoformat():
            # Даже без новых фактов группа может просрочиться или сменить следующую дату.
            touched.update(buckets)
        previous_groups = ForecastInputCodec.decode(previous["groups_snapshot"]).recurrences if previous else []
        grouped = {}
        for group in previous_groups:
            key = old_keys[group.member_transaction_ids[-1]]
            if key not in touched and key in buckets:
                grouped[key] = group
        count = 0
        for key in sorted(touched):
            members = buckets.get(key, [])
            if members and key[3]:
                detected = get_recurrence_detector().detect(members, data.as_of)
                count += 1
                if detected:
                    grouped[key] = detected[0]
        groups = [grouped[key] for key in sorted(grouped)]
        skeleton = {
            "groups_snapshot": ForecastInputCodec.encode(
                replace(
                    data,
                    txns=[],
                    daily_balances=[],
                    planned_events=[],
                    recurrences=groups,
                    scenario=[],
                )
            )
        }
        IncrementalState.check_schedule_budget(data, skeleton)
        excluded = {tid for tid in old.get("excluded", []) if tid in by_id and old_keys[tid] not in touched}
        # Пересматриваем все прежние даты затронутого bucket: новый повтор меняет и старые исключения.
        for key in sorted(touched):
            if key in grouped:
                excluded.update(_recurring_history_ids([grouped[key]], buckets[key]))
        residual = {day: list(pair) for day, pair in old.get("residual", {}).items()}
        new_records = {}
        modified_days = set()
        for tid in records.keys() | by_id.keys():
            prior = records.get(tid)
            txn = by_id.get(tid)
            current = (
                None
                if txn is None
                else {
                    "signature": signatures[tid],
                    "category": txn.category,
                    "bucket": list(self.bucket(txn)),
                    "day": txn.booked_on.isoformat(),
                    "amount": txn.amount_minor,
                    "direction_index": 0 if txn.direction == Direction.IN else 1,
                    "excluded": tid in excluded,
                }
            )
            if current is not None:
                new_records[tid] = current
            for row, sign in ((prior, -1), (current, 1)) if prior != current else ():
                if row is not None and not row["excluded"]:
                    pair = residual.setdefault(row["day"], [0, 0])
                    pair[row["direction_index"]] += sign * row["amount"]
                    modified_days.add(row["day"])
        residual = {day: pair for day, pair in residual.items() if pair != [0, 0]}
        days, warnings, reliable = self.window(data)
        # Окно <=84 дней; сохраняем точную семантику mean и календарные нулевые дни.
        weekday = {}
        for index in range(7):
            samples = [residual.get(day.isoformat(), [0, 0]) for day in days if day.weekday() == index]
            weekday[index] = [mean(pair[i] for pair in samples) if samples else 0 for i in range(2)]
        self.state = {
            "records": new_records,
            "residual": residual,
            "excluded": sorted(excluded),
            "as_of": data.as_of.isoformat(),
        }
        self.metrics = {
            "categorized_transactions": len(changed),
            "reused_transactions": len(txns) - len(changed),
            "recurrence_buckets_recomputed": count,
            "daily_aggregates_changed": len(modified_days),
        }
        by_date = defaultdict(lambda: [0, 0], {date.fromisoformat(day): pair for day, pair in residual.items()})
        return txns, groups, days, warnings, reliable, len(excluded), weekday, by_date

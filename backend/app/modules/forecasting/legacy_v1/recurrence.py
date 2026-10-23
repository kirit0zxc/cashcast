"""Календарные регулярности по повторным датам и устойчивой сумме."""

from __future__ import annotations

import calendar
import hashlib
import itertools
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from app.modules.contracts import Category, RecurrenceGroup, RecurrenceInterval, TxnDTO
from app.modules.forecasting.legacy_v1.categorization import normalize


def advance(day: date, interval: RecurrenceInterval, anchor_day: int | None = None) -> date:
    if interval in {RecurrenceInterval.WEEKLY, RecurrenceInterval.BIWEEKLY}:
        return day + timedelta(days=7 if interval == RecurrenceInterval.WEEKLY else 14)
    months = 1 if interval == RecurrenceInterval.MONTHLY else 3
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(anchor_day or day.day, calendar.monthrange(year, month)[1]))


def _cadence(days: list[date]) -> tuple[RecurrenceInterval, int] | None:
    gaps = [(right - left).days for left, right in itertools.pairwise(days)]
    for interval, period in ((RecurrenceInterval.WEEKLY, 7), (RecurrenceInterval.BIWEEKLY, 14)):
        if all(abs(gap - period) <= 2 for gap in gaps):
            return interval, days[-1].day
    # Якорь 31 сохраняется после февраля; это не фиксированные 30 дней.
    candidate = max(day.day for day in days)
    clipped = all(day.day == min(candidate, calendar.monthrange(day.year, day.month)[1]) for day in days)
    month_end = all(day.day == calendar.monthrange(day.year, day.month)[1] for day in days)
    anchor = 31 if month_end else candidate if clipped else int(median(day.day for day in days))
    for interval, months in ((RecurrenceInterval.MONTHLY, 1), (RecurrenceInterval.QUARTERLY, 3)):
        if all(
            (right.year - left.year) * 12 + right.month - left.month == months
            for left, right in itertools.pairwise(days)
        ) and (clipped or month_end or all(abs(day.day - anchor) <= 3 for day in days)):
            return interval, anchor
    return None


class CalendarRecurrenceDetector:
    def detect(self, txns: list[TxnDTO], as_of: date) -> list[RecurrenceGroup]:
        grouped = defaultdict(list)
        seen = set()
        for txn in sorted(txns, key=lambda t: (t.booked_on, t.id)):
            if txn.booked_on > as_of or txn.amount_minor <= 0 or (txn.account_id, txn.id) in seen:
                continue
            seen.add((txn.account_id, txn.id))
            identity = normalize(txn.counterparty_ref) or normalize(txn.counterparty_name)
            if not identity:
                continue
            category = txn.category if txn.category in {c.value for c in Category} else None
            key = (txn.account_id, txn.currency, txn.direction, identity, category or normalize(txn.purpose))
            grouped[key].append(txn)
        result = []
        for key, members in sorted(grouped.items()):
            daily = defaultdict(int)
            for txn in members:
                daily[txn.booked_on] += txn.amount_minor
            days = sorted(daily)[-6:]
            if len(days) < 3:
                continue
            cadence = _cadence(days)
            typical = int(median(daily[day] for day in days))
            if cadence is None or any(abs(daily[day] - typical) > typical * 0.35 for day in days):
                continue
            interval, anchor = cadence
            expected = advance(days[-1], interval, anchor)
            if expected < as_of - timedelta(days=3):
                continue
            while expected <= as_of:
                expected = advance(expected, interval, anchor)
            selected = [txn for txn in members if txn.booked_on in days]
            group_id = hashlib.sha256(repr(key).encode()).hexdigest()[:24]
            category = selected[-1].category
            result.append(
                RecurrenceGroup(
                    group_id=group_id,
                    direction=selected[-1].direction,
                    interval=interval,
                    typical_amount_minor=typical,
                    counterparty_ref=selected[-1].counterparty_ref,
                    category=Category(category) if category in {c.value for c in Category} else None,
                    confidence=min(0.95, 0.55 + 0.06 * len(days)),
                    member_transaction_ids=[txn.id for txn in selected],
                    next_expected_date=expected,
                    reason=f"Календарное повторение {interval.value}: {len(days)} дат; confidence — сила правила.",
                )
            )
        return result

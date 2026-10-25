"""Окна датасета организаторов: прошлое для модели и сверенный факт по правилам B4."""

import bisect
import calendar
import csv
import hashlib
import io
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from zipfile import ZipFile

import numpy as np
from evaluation.backtest import EXPECTED_SHA256, HOLDOUT, HORIZON, SEED, VALIDATION, fold, temporal_view

from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO
from app.modules.forecasting.legacy_v1.categorization import get_categorizer
from app.modules.forecasting.legacy_v1.factories import get_recurrence_detector
from app.modules.forecasting.legacy_v1.recurrence import advance

LOOKBACK = 84
TRAIN_STEP = 7
# Цель обучающего окна и подтверждающий её остаток заканчиваются до среза модели.
TRAIN_GAP = HORIZON + 7
FIRST_TRAIN = date(2024, 10, 28)


def load(path, companies=None):
    """Как backtest.load_dataset, но с фильтром компаний для smoke-прогона на слабой машине."""
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != EXPECTED_SHA256:
            raise ValueError("Неизвестная версия датасета")
    transactions, balances = defaultdict(list), defaultdict(dict)
    with ZipFile(path) as archive, archive.open("all_operations.csv") as stream:
        for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"), delimiter=";"):
            company = row["company_id"]
            if companies is not None and company not in companies:
                continue
            day = date.fromisoformat(row["operation_date"])
            direction = {"Поступление": Direction.IN, "Списание": Direction.OUT}[row["direction"]]
            transactions[company].append(
                TxnDTO(row["operation_id"], company, day, int(Decimal(row["amount"]) * 100), direction,
                       counterparty_name=row["counterparty_name"] or None,
                       counterparty_ref=row["counterparty_inn"] or None,
                       purpose=row["payment_purpose"] or None)
            )
            balance = int(Decimal(row["balance_eod"]) * 100)
            if balances[company].setdefault(day, balance) != balance:
                raise ValueError("Несогласованные остатки")
    ordered = {c: sorted(t, key=lambda txn: (txn.booked_on, txn.id)) for c, t in transactions.items()}
    return ordered, dict(balances)


@dataclass
class Window:
    company: str
    as_of: date
    cohort: str
    opening: float
    history_days: int
    inc: np.ndarray  # 84 дня до среза включительно; NaN — до первой операции компании
    out: np.ndarray
    bal: np.ndarray  # наблюдаемый EOD с переносом вперёд; NaN — до первого остатка
    rec_in: np.ndarray  # накопленные ожидаемые регулярные поступления на шагах 1..30
    rec_out: np.ndarray
    groups: int
    truth: np.ndarray  # (30, 3): поступления, списания, остаток; только для цели и метрик
    data: ForecastInput | None = None  # вход продукта нужен лишь контрольным окнам
    mismatches84: int = 0  # несверок остатка в окне истории, известных на as_of
    days_since_mismatch: float = np.nan  # дней с последней известной несверки; NaN — не было
    raw_flows: tuple | None = None  # потоки 84 дней без маски качества: масштаб и ориентир «повтор месяца»

    @property
    def label(self) -> int:
        return int((self.truth[:, 2] < 0).any())


class Company:
    """Категории считаются по одной операции, поэтому их можно вычислить один раз."""

    def __init__(self, company, txns, balances):
        assignments = get_categorizer().categorize(txns)
        self.company = company
        self.txns = txns
        self.categorized = [replace(t, category=a.category.value) for t, a in zip(txns, assignments, strict=True)]
        self.by_id = {t.id: t for t in txns}
        self.dates = [t.booked_on for t in txns]
        self.balances = balances
        self.balance_days = sorted(balances)
        self.first = txns[0].booked_on
        # Несверка дня d: остаток(d) − предыдущий наблюдаемый остаток ≠ поток дня d. Она известна с даты d,
        # поэтому для as_of используются только d <= as_of — как в продуктовом quality.py.
        net = defaultdict(int)
        for txn in txns:
            net[txn.booked_on] += txn.amount_minor if txn.direction == Direction.IN else -txn.amount_minor
        self.mismatch_days = [day for previous, day in zip(self.balance_days, self.balance_days[1:], strict=False)
                              if balances[day] - balances[previous] != net[day]]

    def history(self, as_of):
        start = as_of - timedelta(days=LOOKBACK - 1)
        lo, hi = bisect.bisect_left(self.dates, start), bisect.bisect_right(self.dates, as_of)
        inc, out = np.zeros(LOOKBACK), np.zeros(LOOKBACK)
        for txn in self.txns[lo:hi]:
            target = inc if txn.direction == Direction.IN else out
            target[(txn.booked_on - start).days] += txn.amount_minor
        unknown = (self.first - start).days
        if unknown > 0:
            inc[:unknown] = np.nan
            out[:unknown] = np.nan
        index = bisect.bisect_left(self.balance_days, start)
        last = self.balances[self.balance_days[index - 1]] if index else np.nan
        bal = np.empty(LOOKBACK)
        for k in range(LOOKBACK):
            last = self.balances.get(start + timedelta(days=k), last)
            bal[k] = last
        raw = (inc.copy(), out.copy())
        # Маска качества: история до последней известной несверки в окне не считается достоверной.
        recent = [d for d in self.mismatch_days[:bisect.bisect_right(self.mismatch_days, as_of)] if d >= start]
        if recent:
            # Как продукт: потоки дня несверки и раньше неизвестны; остаток этого дня наблюдаем.
            cut = (recent[-1] - start).days
            inc[:cut + 1], out[:cut + 1], bal[:cut] = np.nan, np.nan, np.nan
        return inc, out, bal, raw

    def quality(self, as_of):
        known = self.mismatch_days[:bisect.bisect_right(self.mismatch_days, as_of)]
        start = as_of - timedelta(days=LOOKBACK - 1)
        days_since = float((as_of - known[-1]).days) if known else np.nan
        return sum(d >= start for d in known), days_since

    def recurring(self, as_of):
        # Те же группы и якоря, что продукт кладёт в детерминированную часть прогноза.
        hi = bisect.bisect_right(self.dates, as_of)
        groups = get_recurrence_detector().detect(self.categorized[:hi], as_of)
        rec = {Direction.IN: np.zeros(HORIZON), Direction.OUT: np.zeros(HORIZON)}
        end = as_of + timedelta(days=HORIZON)
        for group in groups:
            members = [self.by_id[i].booked_on for i in group.member_transaction_ids if i in self.by_id]
            anchor = max((d.day for d in members), default=None)
            if members and all(d.day == calendar.monthrange(d.year, d.month)[1] for d in members):
                anchor = 31
            day = group.next_expected_date
            while day is not None and day <= end:
                if day > as_of:
                    rec[Direction(group.direction)][(day - as_of).days - 1] += group.typical_amount_minor
                day = advance(day, group.interval, anchor)
        return np.cumsum(rec[Direction.IN]), np.cumsum(rec[Direction.OUT]), len(groups)

    def window(self, txns, balances, as_of, keep_input):
        entry, reason = fold(self.company, txns, balances, as_of)
        if entry is None:
            return None, reason
        data, truth, cohort = entry
        inc, out, bal, raw = self.history(as_of)
        rec_in, rec_out, groups = self.recurring(as_of)
        return Window(self.company, as_of, cohort, float(data.opening_balance_minor),
                      (as_of - self.first).days + 1, inc, out, bal, rec_in, rec_out, groups,
                      np.array(truth, dtype=float), data if keep_input else None, *self.quality(as_of),
                      raw), None

    def snapshot(self, as_of):
        """Вход моделей на дату as_of только из прошлого: для вызова на одном снимке без факта."""
        days = [day for day in self.balance_days if day <= as_of]
        if not days or (as_of - days[-1]).days > 3:
            raise ValueError("Нужен наблюдаемый остаток не старше 3 дней до as_of")
        past = [txn for txn in self.txns if txn.booked_on <= as_of]
        data = ForecastInput(self.company, as_of, HORIZON, self.balances[days[-1]], SEED, past,
                             [DailyBalanceDTO(self.company, day, self.balances[day]) for day in days], [])
        inc, out, bal, raw = self.history(as_of)
        rec_in, rec_out, groups = self.recurring(as_of)
        age = (as_of - self.first).days + 1
        return Window(self.company, as_of, "short" if age < 90 else "established", float(data.opening_balance_minor),
                      age, inc, out, bal, rec_in, rec_out, groups, np.full((HORIZON, 3), np.nan), data,
                      *self.quality(as_of), raw)


def build(transactions, balances, log=print):
    """Обучающие окна шага7 и контрольные срезы B4 с теми же причинами исключения."""
    view_txns, view_balances = temporal_view(transactions, balances, HOLDOUT)
    last_train = HOLDOUT - timedelta(days=TRAIN_GAP)
    train, control, skipped, train_skipped = [], defaultdict(list), Counter(), Counter()
    for number, company in enumerate(sorted(transactions), 1):
        ctx = Company(company, transactions[company], balances[company])
        day = FIRST_TRAIN
        while day <= last_train:
            item, reason = ctx.window(transactions[company], balances[company], day, False)
            if item is None:
                train_skipped[reason] += 1
            else:
                train.append(item)
            day += timedelta(days=TRAIN_STEP)
        for cutoff in (*VALIDATION, HOLDOUT):
            # Validation, включая проверку полноты целей, не видит строк после 31.08.
            txns, bals = ((transactions[company], balances[company]) if cutoff == HOLDOUT
                          else (view_txns[company], view_balances[company]))
            item, reason = ctx.window(txns, bals, cutoff, True)
            if item is None:
                skipped[f"{cutoff.isoformat()}:{reason}"] += 1
            else:
                control[cutoff].append(item)
        if number % 10 == 0:
            log(f"windows: {number}/{len(transactions)} companies, train={len(train)}")
    return train, dict(control), dict(sorted(skipped.items())), dict(sorted(train_skipped.items()))


def train_for(train, cutoff):
    return [w for w in train if w.as_of + timedelta(days=TRAIN_GAP) <= cutoff]

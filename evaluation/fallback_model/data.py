"""Временные разбиения, сверка целей и равные веса компаний."""

import hashlib
from collections import Counter
from datetime import date, timedelta

import numpy as np

from evaluation.backtest import fold, load_dataset, temporal_view
from .features import DirectFeatures


class Dataset:
    def __init__(self, path):
        self.transactions, self.balances = load_dataset(path)

    @staticmethod
    def heldout(company):
        return hashlib.sha256(company.encode()).digest()[0] % 5 == 0

    def windows(self, cutoffs, limit, heldout=False):
        transactions, balances = temporal_view(self.transactions, self.balances, limit)
        excluded = Counter()
        rows = []
        for cutoff in cutoffs:
            for company, txns in sorted(transactions.items()):
                if self.heldout(company) != heldout:
                    continue
                item, reason = fold(company, txns, balances[company], cutoff)
                if item is None:
                    excluded[reason] += 1
                    continue
                data, truth, cohort = item
                rows.append((data, np.asarray(truth, dtype=np.int64), cohort))
        return rows, dict(excluded)

    def training(self):
        # Последние 30 дней каждого обучающего окна целиком заканчиваются в 2025.
        cutoffs = []
        current = date(2024, 12, 31)
        while current + timedelta(days=30) <= date(2025, 12, 31):
            cutoffs.append(current)
            current += timedelta(days=14)
        rows, excluded = self.windows(cutoffs, date(2025, 12, 31))
        x, y, owners = [], [], []
        used = []
        for data, truth, _ in rows:
            features, scale, quality = DirectFeatures.make(data)
            if quality.history_days < 28:
                excluded["training_history_below_28"] = excluded.get("training_history_below_28", 0) + 1
                continue
            cumulative = np.cumsum(truth[:, :2], axis=0)
            targets = cumulative / scale / np.arange(1, len(truth) + 1)[:, None]
            x.extend(features)
            y.extend(targets)
            owners.extend([data.account_id] * len(truth))
            used.append((data.account_id, data.as_of.isoformat()))
        counts = Counter(owners)
        weights = np.array([len(owners) / len(counts) / counts[owner] for owner in owners])
        return np.asarray(x), np.asarray(y), weights, {
            "rows": len(x), "windows": len(used), "companies": len(counts),
            "target_end": "2025-12-31", "excluded": excluded,
            "window_identity_sha256": hashlib.sha256(repr(used).encode()).hexdigest(),
        }

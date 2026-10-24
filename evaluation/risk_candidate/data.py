"""Плотный train и прежние контрольные окна; границы целей не пересекаются."""

import hashlib
from collections import Counter
from datetime import date

from evaluation.real_data.berka import BerkaDaily
from evaluation.real_data.risk import features

from .features import LiquidityFeatures


class CandidateDataset:
    @staticmethod
    def phase(future_start, future_end, heldout):
        if future_end <= date(1996, 12, 31) and not heldout:
            return "train"
        if future_start.year == future_end.year == 1997 and not heldout:
            return "validation"
        if future_start.year == future_end.year == 1998:
            return "test_unseen_accounts" if heldout else "test_development_accounts"
        return None

    @classmethod
    def build(cls, path):
        groups = {name: [] for name in ("train", "validation", "test_development_accounts", "test_unseen_accounts")}
        audit = {"accounts": 0, "invalid_days": 0, "excluded_windows": 0}
        for account, days, invalid in BerkaDaily.read(path):
            audit["accounts"] += 1
            audit["invalid_days"] += len(invalid)
            heldout = hashlib.sha256(account.encode()).digest()[0] % 5 == 0
            # Шаг7 только для обучения; evaluation сохраняет исходные срезы шага30.
            indices = sorted(set(range(83, len(days) - 30, 7)) | set(range(83, len(days) - 30, 30)))
            for i in indices:
                phase = cls.phase(days[i + 1].date, days[i + 30].date, heldout)
                if phase is None or (i - 83) % (7 if phase == "train" else 30):
                    continue
                history, future = days[i - 83:i + 1], days[i + 1:i + 31]
                if any(day.date in invalid for day in history + future):
                    audit["excluded_windows"] += 1
                    continue
                if history[-1].balance < 0:
                    continue
                groups[phase].append((LiquidityFeatures.build(history), int(any(d.balance < 0 for d in future)),
                                      account, features(history)))
        return groups, audit

    @staticmethod
    def weights(rows):
        counts = Counter(row[2] for row in rows)
        if not counts:
            raise ValueError("Пустая обучающая выборка")
        normalizer = len(rows) / len(counts)
        return [normalizer / counts[row[2]] for row in rows]

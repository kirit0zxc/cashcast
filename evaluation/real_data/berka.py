"""Дневной ряд Berka: проверяем цепочки остатков, а не угадываем EOD по trans_id."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .datasets import Day, minor


class BerkaDaily:
    @staticmethod
    def endpoint(edges, opening):
        # Эйлеров путь использует каждую операцию ровно один раз. Если баланс дня
        # не согласован с предыдущим, такой день и пересекающие его окна исключаются.
        graph = defaultdict(list)
        for start, end in edges:
            graph[start].append(end)
        stack, path = [opening], []
        while stack:
            if graph[stack[-1]]:
                stack.append(graph[stack[-1]].pop())
            else:
                path.append(stack.pop())
        path.reverse()
        if len(path) != len(edges) + 1 or Counter(zip(path, path[1:])) != Counter(
            edges
        ):
            return None
        return path[-1]

    @classmethod
    def read(cls, path: Path):
        grouped = defaultdict(lambda: defaultdict(list))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter=";"):
                kind = row["type"]
                if kind not in {"PRIJEM", "VYDAJ", "VYBER"}:
                    raise ValueError("Неизвестное направление Berka")
                amount, balance = minor(row["amount"]), minor(row["balance"])
                delta = amount if kind == "PRIJEM" else -amount
                day = datetime.strptime(row["date"], "%y%m%d").date()
                grouped[row["account_id"]][day].append(
                    (balance - delta, balance, delta)
                )
        # Обрабатываем по счёту, чтобы не держать миллионы календарных дней в RAM.
        while grouped:
            account, records = grouped.popitem()
            first, last = min(records), max(records)
            opening, series, invalid, trusted = 0, [], set(), True
            for offset in range((last - first).days + 1):
                day = first + timedelta(days=offset)
                rows = records.get(day, [])
                edges = [(r[0], r[1]) for r in rows]
                end = cls.endpoint(edges, opening) if trusted else None
                if end is None:
                    invalid.add(day)
                    # После разрыва пробуем восстановить следующее подтверждённое
                    # окончание, но не используем этот день в обучении или цели.
                    degree = Counter(a for a, _ in edges)
                    degree.subtract(b for _, b in edges)
                    candidates = [
                        vertex for vertex, value in degree.items() if value == 1
                    ]
                    # Замкнутый обход без известного opening неоднозначен, кроме
                    # единственной вершины. Не выбираем остаток по порядку строк.
                    if not candidates and len(degree) == 1:
                        candidates = list(degree)
                    endings = [
                        cls.endpoint(edges, candidate) for candidate in candidates
                    ]
                    valid = [end for end in endings if end is not None]
                    end = valid[0] if len(valid) == 1 else None
                trusted = end is not None
                if end is None:
                    # Это временное число не является фактом: invalid исключает
                    # весь диапазон признаков/цели, пока цепочка не восстановится.
                    end = opening
                incoming = sum(max(r[2], 0) for r in rows)
                outgoing = sum(max(-r[2], 0) for r in rows)
                series.append(Day(day, incoming, outgoing, end))
                opening = end
            yield account, series, invalid

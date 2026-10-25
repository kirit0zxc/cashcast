"""Точный парный bootstrap: прежняя сетка выборки и накопленные дельты траекторий."""

import random
from datetime import date

from app.modules.forecasting.legacy_v1.seasonal import _money


class IncrementalPaths:
    def __init__(self, paths: int):
        self.paths = paths

    def update(self, data, days, future, reliable, residual, previous):
        starts = {
            weekday: [i for i, day in enumerate(days) if day.weekday() == weekday and i + 6 < len(days)]
            for weekday in range(7)
        }
        # Ключ — сами упорядоченные варианты выбора, не только длина окна.
        sampling_key = [data.seed, self.paths, [starts[future[i].weekday()] for i in range(0, len(future), 7)]]
        old_grid = previous.get("sampling_grid", []) if previous else []
        grid = []
        generated = 0
        if reliable:
            if previous and previous.get("sampling_key") == sampling_key and old_grid:
                grid = old_grid
            else:
                generated = self.paths
                grid = [[] for _ in future]
                rng = random.Random(data.seed)  # noqa: S311 -- воспроизводимость frozen-модели
                for _path in range(self.paths):
                    block_start = 0
                    for index, day in enumerate(future):
                        if index % 7 == 0:
                            block_start = rng.choice(starts[day.weekday()])
                        grid[index].append(block_start + index % 7)
        paths = [[] for _ in future]
        changed_cells = 0
        if reliable:
            can_delta = bool(previous and previous["reliable"] and old_grid)
            old_days = [date.fromisoformat(day) for day in previous["days"]] if can_delta else []
            old_residual = previous["history"]["residual"] if can_delta else {}
            for path in range(self.paths):
                accumulated = (
                    data.opening_balance_minor - previous["opening"] if can_delta else data.opening_balance_minor
                )
                for index in range(len(future)):
                    incoming, outgoing = residual[days[grid[index][path]]]
                    delta = _money(incoming * 1.0) - outgoing
                    prior_value = 0
                    if can_delta:
                        old_day = old_days[old_grid[index][path]].isoformat()
                        old_in, old_out = old_residual.get(old_day, [0, 0])
                        delta -= _money(old_in * 1.0) - old_out
                        prior_value = previous["residual_paths"][index][path]
                    accumulated += delta
                    paths[index].append(prior_value + accumulated)
                    changed_cells += not can_delta or accumulated != 0
        self.state = {"sampling_key": sampling_key, "sampling_grid": grid, "opening": data.opening_balance_minor}
        self.metrics = {"bootstrap_paths_generated": generated, "trajectory_values_updated": changed_cells}
        return paths

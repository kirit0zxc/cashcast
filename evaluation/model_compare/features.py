"""Признаки новых моделей. Используются только 84 дня до среза и найденные регулярности."""

import calendar
import warnings
from datetime import timedelta

import numpy as np

from .organizers import HORIZON

STEPS = np.arange(1, HORIZON + 1)
# Порядок колонок совпадает с base()/regression_matrix()/risk_vector(); суффикс _s — деление на scale.
BASE_FEATURES = (
    "opening_s", "log10_scale", "history_days_cap730", "opening_negative",
    "bal_mean7_s", "bal_mean28_s", "bal_mean84_s", "bal_min28_s", "bal_min84_s", "bal_max84_s",
    "bal_change7_s", "bal_change28_s", "bal_change83_s",
    "inc_mean7_s", "inc_mean28_s", "inc_mean84_s", "out_mean7_s", "out_mean28_s", "out_mean84_s",
    "inc_std84_s", "out_std84_s", "inc_nonzero_share84", "out_nonzero_share84",
    "days_since_inflow", "negative_eod_days84", "net_mean84_s",
    "recurrence_groups", "rec_in_horizon_s", "rec_out_horizon_s",
    "unreconciled_days84", "days_since_unreconciled",
)
STEP_FEATURES = (
    "h", "weekday", "day_of_month", "month", "days_to_month_end",
    "naive_month_cumnet_s", "naive_2month_cumnet_s", "naive_avg_cumnet_s", "weekday_profile_cumnet_s",
    "recurring_cumnet_s", "rec_in_cum_s", "rec_out_cum_s", "weekday_plus_recurring_cumnet_s",
    "inc_same_day_last30_s", "out_same_day_last30_s",
)
RISK_EXTRA_FEATURES = (
    "min_naive_month_s", "min_naive_2month_s", "min_weekday_profile_s", "min_recurring_s",
    "min_weekday_plus_recurring_s",
)
REGRESSION_FEATURES = BASE_FEATURES + STEP_FEATURES
RISK_FEATURES = BASE_FEATURES + RISK_EXTRA_FEATURES


def _nan(function, values):
    # Пустой участок истории остаётся неизвестным (NaN), а не превращается в ноль.
    values = values[np.isfinite(values)]
    return float(function(values)) if values.size else np.nan


def scale(window) -> float:
    # Нормировка по обороту: одна глобальная модель на компаниях разного размера.
    # Масштаб — оборот по сырым 84 дням: маска качества скрывает признаки, но не размер компании.
    inc, out = window.raw_flows if window.raw_flows is not None else (window.inc, window.out)
    flows = (np.nan_to_num(_nan(np.mean, inc)), np.nan_to_num(_nan(np.mean, out)))
    return max(10_000.0, *flows)


def _paths(window):
    """Простые траектории чистого потока: прошлый месяц, позапрошлый, профиль недели, регулярности."""
    inc, out = window.inc, window.out
    net = inc - out
    known = np.isfinite(net)
    days = [window.as_of - timedelta(days=len(net) - 1 - k) for k in range(len(net))]
    profile = np.zeros(7)
    for weekday in range(7):
        mask = known & np.array([d.weekday() == weekday for d in days])
        profile[weekday] = net[mask].mean() if mask.any() else np.nan
    future = [window.as_of + timedelta(days=int(h)) for h in STEPS]
    weekly = np.cumsum([profile[d.weekday()] for d in future])
    return {
        # Траектория по месяцу неизвестна, если в нём есть неизвестные дни: ноль не подставляется.
        "month": np.cumsum(net[-30:]),
        "two_months": np.cumsum(net[-60:-30]),
        "weekday": weekly,
        "recurring": window.rec_in - window.rec_out,
        "inc_prev": inc[-30:],
        "out_prev": out[-30:],
        "future": future,
    }


def base(window, s):
    inc, out, bal = window.inc, window.out, window.bal
    net = inc - out
    o = window.opening
    paid = np.flatnonzero(np.nan_to_num(inc) > 0)
    known_inc, known_out = inc[np.isfinite(inc)], out[np.isfinite(out)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return [
            o / s, np.log10(s), min(window.history_days, 730), float(o < 0),
            _nan(np.mean, bal[-7:]) / s, _nan(np.mean, bal[-28:]) / s, _nan(np.mean, bal) / s,
            _nan(np.min, bal[-28:]) / s, _nan(np.min, bal) / s, _nan(np.max, bal) / s,
            (o - bal[-8]) / s, (o - bal[-29]) / s, (o - bal[0]) / s,
            _nan(np.mean, inc[-7:]) / s, _nan(np.mean, inc[-28:]) / s, _nan(np.mean, inc) / s,
            _nan(np.mean, out[-7:]) / s, _nan(np.mean, out[-28:]) / s, _nan(np.mean, out) / s,
            _nan(np.std, inc) / s, _nan(np.std, out) / s,
            (known_inc > 0).mean() if known_inc.size else np.nan,
            (known_out > 0).mean() if known_out.size else np.nan,
            len(inc) - 1 - paid[-1] if paid.size else np.nan,
            float(np.nansum(bal < 0)), _nan(np.mean, net) / s,
            window.groups, window.rec_in[-1] / s, window.rec_out[-1] / s,
            window.mismatches84, window.days_since_mismatch,
        ]


def regression_matrix(window):
    """Матрица (30, F) прямой многошаговой модели: шаг h — отдельная строка."""
    s = scale(window)
    p = _paths(window)
    days = p["future"]
    per_step = np.column_stack([
        STEPS,
        [d.weekday() for d in days],
        [d.day for d in days],
        [d.month for d in days],
        [calendar.monthrange(d.year, d.month)[1] - d.day for d in days],
        p["month"] / s, p["two_months"] / s, (p["month"] + p["two_months"]) / (2 * s),
        p["weekday"] / s, p["recurring"] / s, window.rec_in / s, window.rec_out / s,
        (p["weekday"] + p["recurring"]) / s, p["inc_prev"] / s, p["out_prev"] / s,
    ])
    return np.hstack([np.tile(base(window, s), (HORIZON, 1)), per_step]).astype(np.float32), s


def regression_targets(window, s):
    """Изменение остатка и дневные потоки в долях оборота."""
    t = window.truth
    return (t[:, 2] - window.opening) / s, t[:, 0] / s, t[:, 1] / s


def risk_vector(window):
    """Признаки окна для вероятности хотя бы одного минуса за горизонт."""
    s = scale(window)
    p = _paths(window)
    o = window.opening
    lows = [(o + p[name]).min() / s for name in ("month", "two_months", "weekday", "recurring")]
    lows.append((o + p["weekday"] + p["recurring"]).min() / s)
    return base(window, s) + lows


def naive_month(window):
    """Сезонный naive: повтор потоков прошлых 30 дней поверх текущего остатка."""
    inc, out = (np.nan_to_num(a[-30:]) for a in window.raw_flows)
    return window.opening + np.cumsum(inc - out), inc, out

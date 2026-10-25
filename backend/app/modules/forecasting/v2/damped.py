"""Версия2.2: центр траекторий2.1 затухает к остатку на as_of, разброс bootstrap сохраняется.

Ресёрч MAE 25.10.2026: на всех срезах persistence точнее2.1, а прогнозируемое2.1 изменение остатка
не несёт сигнала. Изменение раскладывается на нерегулярный дрейф bootstrap (α) и найденные регулярные
платежи (β). Каждая траектория дня сдвигается на одну величину, поэтому p10/p90 смещаются
вместе с p50, ширина интервала не меняется, а риск считается по тем же сдвинутым траекториям.
Коэффициенты подобраны только на срезах validation 30.04–31.07.2026 (evaluation/damping_fit.py, Colab
25.10.2026). На каждом срезе расширяющегося окна подбор давал α = 0: дрейф bootstrap не помогает
ни на одном горизонте, а регулярности полезны лишь на первой неделе и с малым весом (β 0,1–0,4).
"""

from collections import defaultdict
from dataclasses import replace
from fractions import Fraction

from app.modules.contracts import Direction, ForecastInput, ForecastResult
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService, _money, _quantile
from app.modules.forecasting.v2.estimated import EstimatedForecastService
from app.modules.forecasting.v2.incremental_engine import IncrementalSeasonalService

MODEL_VERSION = "seasonal-damped-2.2-w84"
POINT_METHOD = "seasonal-block-bootstrap-1.0-w84+damping-2.2"
# Дни горизонта → (α нерегулярного дрейфа, β графика). После 30-го дня действует последняя корзина.
DAMPING = {(1, 7): (0.0, 0.1), (8, 14): (0.0, 0.0), (15, 21): (0.0, 0.0), (22, 30): (0.0, 0.0)}
# α для детерминированного пути средних, когда истории для bootstrap недостаточно.
UNRELIABLE_DRIFT = 0.0
SCENARIO_REASON = (
    "Для сценария версия2.2 сдвигает квантили, но не пересчитывает траектории: вероятность минуса недоступна."
)
FLOWS_ASSUMPTION = (
    "Версия2.2: p10/p50/p90 затухают к текущему остатку (details.damping); inflow/outflow — прогноз потоков"
    " без затухания, их сумма не равна изменению p50."
)
HORIZON_WARNING = "Затухание2.2 подобрано на горизонте30 дней; после30-го дня действует последняя корзина без проверки."


def coefficients(day: int) -> tuple[float, float]:
    for (first, last), pair in DAMPING.items():
        if first <= day <= last:
            return pair
    return DAMPING[max(DAMPING)]


def shifts(reference: ForecastResult, opening: int) -> list[int]:
    """Сдвиг дня = (α−1)·дрейф + (β−1)·регулярности по прогнозу reference, в копейках.

    p50 = остаток + медианный дрейф + весь график, поэтому дрейф восстанавливается из опубликованной
    медианы. Плановые события и расходы сценария введены пользователем как известные и не затухают.
    Дроби вместо float: суммы до MAX_MONEY_MINOR не теряют точность, округление одно — на границе.
    """
    reliable = reference.details["paths"] > 0
    recurring = defaultdict(int)
    for item in reference.details["explanations"]:
        if item["kind"] == "recurrence":
            sign = 1 if item["detail"]["direction"] == Direction.IN.value else -1
            recurring[item["detail"]["date"]] += sign * item["amount_minor"]
    known, regular, result = 0, 0, []
    for day, (point, component) in enumerate(
            zip(reference.points, reference.details["daily_components"], strict=True), 1):
        known += component["planned_in_minor"] - component["planned_out_minor"]
        regular += recurring[point.point_date.isoformat()]
        alpha, beta = coefficients(day)
        alpha = alpha if reliable else UNRELIABLE_DRIFT
        drift = point.balance_p50_minor - opening - known
        result.append(_money((Fraction(str(alpha)) - 1) * drift + (Fraction(str(beta)) - 1) * regular))
    return result


def damp(result: ForecastResult, data: ForecastInput, residual_paths: list[list[int]] | None,
         reference: ForecastResult | None = None) -> ForecastResult:
    """Сдвигает прогноз result; residual_paths — траектории без графика, None — путей нет.

    reference — прогноз, по которому считается затухание. Для сценария это база без сценария:
    сценарий = затухший базовый прогноз + полный эффект сценария, иначе α = 0 стёр бы снижение выручки.
    """
    known, points, trajectories = 0, [], []
    day_shifts = shifts(reference or result, data.opening_balance_minor)
    for day, (point, component, shift) in enumerate(
            zip(result.points, result.details["daily_components"], day_shifts, strict=True), 1):
        known += component["planned_in_minor"] - component["planned_out_minor"]
        if residual_paths is None:
            # Без траекторий квантили сдвигаются на ту же величину; вероятность пересчитать нельзя.
            points.append(replace(point, balance_p10_minor=point.balance_p10_minor + shift,
                                  balance_p50_minor=point.balance_p50_minor + shift,
                                  balance_p90_minor=point.balance_p90_minor + shift, probability_negative=None))
            continue
        values = [value + known + shift for value in residual_paths[day - 1]]
        trajectories.append(values)
        points.append(replace(point, balance_p10_minor=_quantile(values, 0.1), balance_p50_minor=_quantile(values, 0.5),
                              balance_p90_minor=_quantile(values, 0.9),
                              probability_negative=sum(value < 0 for value in values) / len(values)))
    negative = [point for point in points if point.balance_p50_minor < 0]
    probability = None
    if trajectories:
        paths = len(trajectories[0])
        probability = sum(any(day[path] < 0 for day in trajectories) for path in range(paths)) / paths
    refs = sorted({
        item["source_ref"] for item in result.details["explanations"]
        if item["kind"] == "planned" and item["source_ref"] and item["detail"]["direction"] == Direction.OUT.value
        and negative and item["detail"]["date"] <= negative[0].point_date.isoformat()
    })
    risk = replace(
        result.risk,
        available=result.risk.available and residual_paths is not None,
        first_negative_date=negative[0].point_date if negative else None,
        max_deficit_minor=max(-point.balance_p50_minor for point in negative) if negative else None,
        probability_any_negative=probability if result.risk.available else None,
        related_event_ids=refs,
    )
    damping = {"by_days": [{"from": first, "to": last, "drift_alpha": a, "schedule_beta": b}
                           for (first, last), (a, b) in DAMPING.items()],
               "unreliable_drift_alpha": UNRELIABLE_DRIFT}
    warnings = [*result.data_warnings, *([HORIZON_WARNING] if data.horizon_days > 30 else [])]
    return replace(result, points=points, risk=risk, assumptions=[*result.assumptions, FLOWS_ASSUMPTION],
                   data_warnings=warnings, details={**result.details, "damping": damping})


class DampedIncrementalService(IncrementalSeasonalService):
    # Денежный guard остаётся в GuardedForecastService и проверяет уже затухший результат.
    def run(self, data: ForecastInput, prepared: dict | None = None) -> ForecastResult:
        result = super().run(data, prepared)
        # Сохранённые для дельты траектории остаются исходными: checkpoint совместим с2.1.
        residual_paths = self.prepared["residual_paths"] if self.prepared["reliable"] else None
        return damp(result, data, residual_paths)


class DampedScenarioService(SeasonalForecastService):
    def run(self, data: ForecastInput) -> ForecastResult:
        # Тот же seed и та же сетка bootstrap: разность сценария и базы — чистый эффект изменений.
        base = super().run(replace(data, scenario=[]))
        return damp(super().run(data), data, None, reference=base)


class DampedForecastService(EstimatedForecastService):
    engine_type = DampedIncrementalService
    scenario_type = DampedScenarioService

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def finalize_probability(self, raw, output, quality, data):
        output = super().finalize_probability(raw, output, quality, data)
        details = {**output.details, "point_method_version": POINT_METHOD}
        warnings = output.data_warnings
        # Заменяем причину, только если без сценария вероятность была бы доступна.
        if data.scenario and quality.eligible_for_probability and raw.details["paths"] > 0:
            previous = details["risk_probability"]["reason"]
            details["risk_probability"] = {**details["risk_probability"], "reason": SCENARIO_REASON}
            warnings = [SCENARIO_REASON if value == previous else value for value in warnings]
        return replace(output, details=details, data_warnings=warnings)

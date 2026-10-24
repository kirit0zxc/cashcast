"""Версия2.1 публикует долю симуляций с минусом как некалиброванную модельную оценку."""

from dataclasses import replace

from app.modules.forecasting.v2.service import GuardedForecastService

MODEL_VERSION = "seasonal-estimated-2.1-w84"
ESTIMATE_WARNING = (
    "Вероятность минуса — доля смоделированных траекторий, а не проверенная частота реальных разрывов. "
    "Оценка не откалибрована; 0% и 100% в симуляции не являются гарантией."
)


class EstimatedForecastService(GuardedForecastService):
    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def finalize_probability(self, raw, output, quality, data):
        available = quality.eligible_for_probability and raw.risk.available
        probability = raw.risk.probability_any_negative if available else None
        points = [replace(point, probability_negative=source.probability_negative if available else None)
                  for point, source in zip(output.points, raw.points, strict=True)]
        risk = replace(output.risk, available=available, probability_any_negative=probability)
        reason = (ESTIMATE_WARNING if available else
                  "Недостаточно пригодной истории или актуального согласованного остатка: вероятность недоступна.")
        details = {**output.details,
                   "summary": "Прогноз потоков, остатка и модельная оценка вероятности минуса.",
                   "risk_probability": {
                       "policy_version": "risk-policy-2.1-uncalibrated-estimate",
                       "status": "estimated_uncalibrated" if available else "unavailable",
                       "probability_any_negative": probability,
                       "calibrated": False, "paths": raw.details["paths"] if available else 0,
                       "scope": "any_negative_future_balance",
                       "opening_already_negative": data.opening_balance_minor < 0,
                       "reason": reason,
                   }}
        warnings = [value for value in output.data_warnings if value !=
                    "Вероятность нового кассового разрыва не подтверждена; None отличается от нулевого риска."]
        warnings.append(reason)
        return replace(output, points=points, risk=risk, details=details, data_warnings=warnings)

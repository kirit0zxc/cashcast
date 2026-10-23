"""Точка входа модуля прогноза. Пока отдаёт baseline; Данил заменит на финальную модель.

Публичный интерфейс для backend — функция get_forecast_service(). Остальной код
обращается только к ней, поэтому замена реализации не затронет API и worker.
"""

from __future__ import annotations

from app.modules.contracts import ForecastService
from app.modules.forecasting.baseline import BaselineForecastService


def get_forecast_service() -> ForecastService:
    # TODO(Данил): вернуть здесь свою модель (сезонный baseline + ETS + бутстрап риска),
    # сохранив контракт ForecastService.run(ForecastInput) -> ForecastResult.
    return BaselineForecastService()

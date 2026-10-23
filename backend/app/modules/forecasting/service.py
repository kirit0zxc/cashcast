"""Публичная фабрика аналитического прогноза по согласованному ForecastService."""

from __future__ import annotations

from app.modules.contracts import ForecastService
from app.modules.forecasting.seasonal import SeasonalForecastService


def get_forecast_service() -> ForecastService:
    return SeasonalForecastService()

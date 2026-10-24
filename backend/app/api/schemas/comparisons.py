"""Сравнение сценария с его закреплённой базой (comparison-v1 A006/B012)."""

from datetime import date

from pydantic import BaseModel

from app.api.schemas.models import RiskOut


class ComparedPoint(BaseModel):
    point_date: date
    base_balance_p50_minor: int
    scenario_balance_p50_minor: int
    delta_balance_minor: int


class ComparedRisk(BaseModel):
    base: RiskOut
    scenario: RiskOut


class ForecastComparison(BaseModel):
    base_forecast_id: str
    scenario_forecast_id: str
    as_of: date
    horizon_days: int
    model_version: str
    points: list[ComparedPoint]
    risk: ComparedRisk

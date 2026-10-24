"""Публичный отчёт качества: измерения отделены от прогноза конкретного счёта."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


class QualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class QualityMetric(QualityModel):
    value: float | None
    definition: str
    unavailable_reason: str | None = None


class QualityCohort(QualityModel):
    name: str
    windows: int
    accounts: int
    positive_windows: int
    positive_accounts: int
    threshold: float
    confusion_matrix: dict[str, int]
    metrics: dict[str, QualityMetric]
    uncertainty: JsonValue


class QualityEvidence(QualityModel):
    path: str
    sha256: str
    hash_format: Literal["utf8_lf"]
    data: JsonValue


class ModelQualityOut(QualityModel):
    report_version: Literal["model-quality-1.0"]
    scope: Literal["offline_external_evaluation"]
    evaluated_model: str
    production_activated: Literal[False]
    applies_to_current_forecast: Literal[False]
    probability_calibrated: Literal[False]
    horizon_days: int
    label_definition: str
    cohorts: list[QualityCohort]
    calibration: JsonValue
    selection_policy: JsonValue
    release: JsonValue
    evidence: list[QualityEvidence]
    limitations: list[str]

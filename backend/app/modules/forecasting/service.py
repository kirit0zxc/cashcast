"""Статический реестр закреплённых версий, согласованный model-registry-v2."""

from __future__ import annotations

from dataclasses import replace

from app.modules.contracts import Direction, ForecastInput, ForecastResult, ForecastService
from app.modules.forecasting.legacy_v1.baseline import MODEL_VERSION as BASELINE_VERSION
from app.modules.forecasting.legacy_v1.baseline import BaselineForecastService
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService
from app.modules.forecasting.v2.damped import MODEL_VERSION as DAMPED_VERSION
from app.modules.forecasting.v2.damped import DampedForecastService
from app.modules.forecasting.v2.estimated import MODEL_VERSION as ESTIMATED_VERSION
from app.modules.forecasting.v2.estimated import EstimatedForecastService
from app.modules.forecasting.v2.legacy_limits import check_legacy_cost, check_output_budget
from app.modules.forecasting.v2.quality import validate_input
from app.modules.forecasting.v2.service import MODEL_VERSION as GUARDED_VERSION
from app.modules.forecasting.v2.service import GuardedForecastService

DEFAULT_MODEL_VERSION = DAMPED_VERSION
_SUPPORTED = (
    BASELINE_VERSION,
    "seasonal-block-bootstrap-1.0-w28",
    "seasonal-block-bootstrap-1.0-w56",
    "seasonal-block-bootstrap-1.0-w84",
    GUARDED_VERSION,
    ESTIMATED_VERSION,
    DAMPED_VERSION,
)


class UnsupportedModelVersionError(ValueError):
    code = "unsupported_model_version"

    def __init__(self):
        super().__init__("unsupported_model_version: версия отсутствует в статическом реестре")


class _PinnedLegacyService:
    """Математика1.0 заморожена; неподдерживаемый/слишком большой вход отвергается явно."""

    def __init__(self, version: str):
        self._version = version
        self._service = (
            BaselineForecastService()
            if version == BASELINE_VERSION
            else SeasonalForecastService(lookback_days=int(version.rsplit("w", 1)[1]))
        )

    @property
    def model_version(self) -> str:
        return self._version

    def run(self, data: ForecastInput) -> ForecastResult:
        data = validate_input(data)
        data = replace(
            data,
            txns=[replace(txn, direction=Direction(txn.direction)) for txn in data.txns],
            planned_events=[replace(event, direction=Direction(event.direction)) for event in data.planned_events],
        )
        if self.model_version != BASELINE_VERSION:
            check_legacy_cost(data)
        result = self._service.run(data)
        check_output_budget(result)
        if result.model_version != self.model_version:
            raise RuntimeError("Закреплённая модель вернула другую версию")
        return result


def get_supported_model_versions() -> tuple[str, ...]:
    return _SUPPORTED


def get_forecast_service(model_version: str | None = None) -> ForecastService:
    version = DEFAULT_MODEL_VERSION if model_version is None else model_version
    if not isinstance(version, str) or version not in _SUPPORTED:
        raise UnsupportedModelVersionError()
    if version == ESTIMATED_VERSION:
        return EstimatedForecastService()
    if version == DAMPED_VERSION:
        return DampedForecastService()
    return GuardedForecastService() if version == GUARDED_VERSION else _PinnedLegacyService(version)

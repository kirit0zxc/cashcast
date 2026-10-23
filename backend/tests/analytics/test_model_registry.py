"""Статический реестр и отказ от тихой подмены закреплённой модели."""

from dataclasses import replace

import pytest

from app.modules.forecasting.service import (
    DEFAULT_MODEL_VERSION,
    UnsupportedModelVersionError,
    get_forecast_service,
    get_supported_model_versions,
)
from tests.analytics.test_seasonal import history


@pytest.mark.parametrize("version", get_supported_model_versions())
def test_registered_version_matches_output(version):
    service = get_forecast_service(version)
    assert service.model_version == version
    assert service.run(history()).model_version == version


@pytest.mark.parametrize("version", ["", "unknown", "seasonal-block-bootstrap-1.0-w7", "../../module", [], True])
def test_unknown_version_does_not_fall_back(version):
    with pytest.raises(UnsupportedModelVersionError, match="unsupported_model_version"):
        get_forecast_service(version)


def test_default_and_resource_guard():
    service = get_forecast_service()
    assert service.model_version == DEFAULT_MODEL_VERSION
    with pytest.raises(ValueError, match="invalid_forecast_input"):
        service.run(replace(history(), horizon_days=181))
    assert isinstance(get_supported_model_versions(), tuple)

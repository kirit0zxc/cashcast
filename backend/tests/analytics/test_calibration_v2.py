"""Ручные примеры вероятностей: None не кодируется как отсутствие риска."""

import math

import pytest

from app.modules.forecasting.v2.calibration import CalibrationModel, bin_index, fit_calibrators


def test_fit_prior_intercept_and_monotonicity():
    observations = [(0.1, 0)] * 80 + [(0.8, 1)] * 20
    models = fit_calibrators(observations)
    prevalence = 21 / 102
    assert models["constant"].predict(1) == prevalence
    adjusted = sum(models["logit_intercept"].predict(probability) for probability, _ in observations) / 100
    assert math.isclose(adjusted, prevalence, abs_tol=1e-12)
    for model in models.values():
        values = [model.predict(index / 100) for index in range(101)]
        assert values == sorted(values)
        assert all(0 <= value <= 1 for value in values)
        assert CalibrationModel(model.kind, model.parameters).to_dict() == model.to_dict()


def test_pava_pools_violations_with_declared_prior():
    models = fit_calibrators([(0.05, 1)] * 10 + [(0.15, 0)] * 10)
    # Обратный порядок факта объединён PAVA, а не остаётся убывающей функцией.
    assert models["pava"].predict(0.05) == models["pava"].predict(0.15)
    assert models["pava"].predict(0.05) == 0.5
    assert bin_index(0) == 0 and bin_index(1) == 5
    assert bin_index(0.1) == 1


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -0.1, 1.1, True, "0.1"])
def test_invalid_probability_explicit(value):
    with pytest.raises(ValueError):
        CalibrationModel("raw").predict(value)


def test_empty_and_invalid_fit_and_models_rejected():
    for values in ([], [(0.1, 2)], [(0.1, None)]):
        with pytest.raises(ValueError):
            fit_calibrators(values)
    for kind, parameters in [
        ("unknown", ()),
        ("constant", (2,)),
        ("raw", (1,)),
        ("pava", (1, 0, 0, 0, 0, 0)),
        ("logit_intercept", (float("nan"),)),
    ]:
        with pytest.raises(ValueError):
            CalibrationModel(kind, parameters)

"""Веса обученных моделей: текстовые бустеры LightGBM и JSON логистической регрессии, без pickle."""

import json

import lightgbm as lgb
import numpy as np

from .models import MIN_QUANTILES, QUANTILES, GlobalLightGBM, RiskModels


def _q(alpha):
    return f"{alpha:.3f}".rstrip("0").rstrip(".").replace(".", "_")


class Booster:
    """Загруженный бустер с тем же интерфейсом, что у sklearn-обёртки LightGBM."""

    def __init__(self, path):
        self.booster = lgb.Booster(model_file=str(path))

    def predict(self, x):
        return self.booster.predict(x)

    def predict_proba(self, x):
        p = self.booster.predict(x)
        return np.column_stack([1 - p, p])


class Logistic:
    """Логистическая регрессия из JSON: медианная импутация, стандартизация, сигмоида."""

    def __init__(self, params):
        self.median, self.mean, self.scale, self.coef = (
            np.array(params[k]) for k in ("impute_median", "mean", "scale", "coef"))
        self.intercept = params["intercept"]

    def predict_proba(self, x):
        x = np.where(np.isnan(x), self.median, x)
        p = 1 / (1 + np.exp(-(((x - self.mean) / self.scale) @ self.coef + self.intercept)))
        return np.column_stack([1 - p, p])


def _logistic_params(pipeline):
    imputer, scaler, logistic = (step for _, step in pipeline.steps)
    return {"impute_median": imputer.statistics_.tolist(), "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(), "coef": logistic.coef_[0].tolist(),
            "intercept": float(logistic.intercept_[0])}


def save(regressor, risk, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for alpha, model in regressor.balance.items():
        model.booster_.save_model(str(folder / f"balance_delta_q{_q(alpha)}.txt"))
    for name, model in zip(("inflow_mean", "outflow_mean"), regressor.flows, strict=True):
        model.booster_.save_model(str(folder / f"{name}.txt"))
    meta = {"new_gap_prior": risk.new_gap_prior, "new_gap_single_class": risk.new_gap_single_class,
            "prior": risk.prior, "persistence_negative_opening": risk.persistence[0],
            "persistence_nonnegative_opening": risk.persistence[1], "single_class": risk.single_class,
            "train_windows": risk.rows, "train_positive_windows": risk.positives}
    if not risk.new_gap_single_class:
        risk.new_gap_classifier.booster_.save_model(str(folder / "new_gap_lgbm_classifier.txt"))
        meta["new_gap_logistic"] = _logistic_params(risk.new_gap_logistic)
    if not risk.single_class:
        risk.classifier.booster_.save_model(str(folder / "risk_lgbm_classifier.txt"))
        for alpha, model in risk.lows.items():
            model.booster_.save_model(str(folder / f"risk_min_balance_q{_q(alpha)}.txt"))
        meta["logistic"] = _logistic_params(risk.logistic)
    (folder / "risk.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def load(folder):
    """Модели одного среза из папки save(); предсказания совпадают с обученными объектами."""
    regressor = GlobalLightGBM()
    regressor.balance = {a: Booster(folder / f"balance_delta_q{_q(a)}.txt") for a in QUANTILES}
    regressor.flows = [Booster(folder / f"{name}.txt") for name in ("inflow_mean", "outflow_mean")]
    meta = json.loads((folder / "risk.json").read_text(encoding="utf-8"))
    risk = RiskModels()
    risk.prior, risk.single_class = meta["prior"], meta["single_class"]
    risk.new_gap_prior, risk.new_gap_single_class = meta["new_gap_prior"], meta["new_gap_single_class"]
    if not risk.new_gap_single_class:
        risk.new_gap_classifier = Booster(folder / "new_gap_lgbm_classifier.txt")
        risk.new_gap_logistic = Logistic(meta["new_gap_logistic"])
    risk.persistence = (meta["persistence_negative_opening"], meta["persistence_nonnegative_opening"])
    if not risk.single_class:
        risk.classifier = Booster(folder / "risk_lgbm_classifier.txt")
        risk.lows = {a: Booster(folder / f"risk_min_balance_q{_q(a)}.txt") for a in MIN_QUANTILES}
        risk.logistic = Logistic(meta["logistic"])
    return regressor, risk

"""Модели сравнения. Гиперпараметры заморожены в MODEL-COMPARE-PLAN.md до запуска."""

import lightgbm as lgb
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.modules.forecasting.service import get_forecast_service

from .features import naive_month, regression_matrix, regression_targets, risk_vector, scale

SEED = 42
CURRENT = "seasonal-estimated-2.1-w84"
REFERENCE = "seasonal-block-bootstrap-1.0-w84"
BASELINE = "baseline-repeat-week-0.1"
QUANTILES = (0.1, 0.5, 0.9)
MIN_QUANTILES = (0.01, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95)
COMMON = {"random_state": SEED, "deterministic": True, "force_row_wise": True, "verbose": -1,
          "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8}
REGRESSOR = {**COMMON, "n_estimators": 400, "learning_rate": 0.05, "num_leaves": 31,
             "min_child_samples": 200, "reg_lambda": 1.0, "max_bin": 127}
WINDOW_REGRESSOR = {**COMMON, "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
                    "min_child_samples": 50, "reg_lambda": 5.0}
CLASSIFIER = {**COMMON, "n_estimators": 300, "learning_rate": 0.03, "num_leaves": 15,
              "min_child_samples": 50, "reg_lambda": 5.0}


def _params(params, smoke):
    # Smoke-прогон проверяет код на слабой машине; его числа не являются результатом.
    return {**params, "n_estimators": 30} if smoke else params


def _logistic():
    # keep_empty_features: колонка целиком из NaN не выпадает, и размерность весов совпадает с признаками.
    return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(),
                         LogisticRegression(C=0.1, max_iter=5000))


class ProductModel:
    """Закреплённая версия из реестра продукта, без изменения её кода и параметров."""

    def __init__(self, version):
        self.version = version
        self.service = get_forecast_service(version)

    def predict(self, window):
        result = self.service.run(window.data)
        if result.model_version != self.version:
            raise RuntimeError("Реестр вернул другую версию модели")
        points = result.points
        return {
            "p10": np.array([p.balance_p10_minor for p in points], dtype=float),
            "p50": np.array([p.balance_p50_minor for p in points], dtype=float),
            "p90": np.array([p.balance_p90_minor for p in points], dtype=float),
            "inc": np.array([p.inflow_minor for p in points], dtype=float),
            "out": np.array([p.outflow_minor for p in points], dtype=float),
            "risk": result.risk.probability_any_negative,
        }


def naive_prediction(window):
    balance, inc, out = naive_month(window)
    return {"p10": None, "p50": balance, "p90": None, "inc": inc, "out": out}


def persistence_prediction(window):
    """Ориентир аудита: остаток не меняется, потоков нет, интервала нет."""
    flat = np.full(len(window.truth), window.opening)
    return {"p10": None, "p50": flat, "p90": None, "inc": np.zeros(len(flat)), "out": np.zeros(len(flat))}


def ensemble(first, second):
    """Равные веса заданы заранее. Квантили усредняются (Vincentization), это не квантили смеси."""
    return {key: None if first[key] is None or second[key] is None else (first[key] + second[key]) / 2
            for key in ("p10", "p50", "p90", "inc", "out")}


class GlobalLightGBM:
    """v2: одна прямая модель на все компании; цели без обрезки, потоки — Huber."""

    def fit(self, windows, smoke=False):
        rows, targets = [], ([], [], [])
        for window in windows:
            x, s = regression_matrix(window)
            rows.append(x)
            for bucket, values in zip(targets, regression_targets(window, s), strict=True):
                bucket.append(values)
        x = np.vstack(rows)
        delta, inc, out = (np.concatenate(bucket) for bucket in targets)
        params = _params(REGRESSOR, smoke)
        self.balance = {
            alpha: lgb.LGBMRegressor(objective="quantile", alpha=alpha, **params).fit(x, delta)
            for alpha in QUANTILES
        }
        # Хвосты потоков не обрезаются: устойчивость даёт Huber с порогом в один дневной оборот.
        self.flows = [lgb.LGBMRegressor(objective="huber", alpha=1.0, **params).fit(x, y) for y in (inc, out)]
        self.rows = len(x)
        return self

    def predict(self, window):
        x, s = regression_matrix(window)
        # Сортировка исключает пересечение квантилей отдельных моделей.
        q = np.sort(np.column_stack([self.balance[a].predict(x) for a in QUANTILES]), axis=1)
        p10, p50, p90 = (window.opening + s * q[:, i] for i in range(3))
        inc, out = (np.maximum(0.0, s * model.predict(x)) for model in self.flows)
        return {"p10": p10, "p50": p50, "p90": p90, "inc": inc, "out": out}


class RiskModels:
    """Вероятность хотя бы одного отрицательного EOD за 30 дней."""

    NAMES = ("LightGBM-классификатор", "Логистическая регрессия", "LightGBM квантили минимума",
             "Константа (частота train)", "Persistence (знак остатка)")
    # Модели нового разрыва учатся только на окнах с остатком на as_of >= 0.
    NEW_GAP = ("Новый разрыв: LightGBM", "Новый разрыв: логистическая", "Новый разрыв: частота train")

    def fit(self, windows, smoke=False):
        x = np.array([risk_vector(w) for w in windows], dtype=float)
        y = np.array([w.label for w in windows])
        negative = x[:, 3] > 0
        self.prior = float(y.mean())
        self.persistence = (float(y[negative].mean()) if negative.any() else 1.0,
                            float(y[~negative].mean()) if (~negative).any() else self.prior)
        self.rows, self.positives = len(y), int(y.sum())
        nonnegative = ~negative
        self.new_gap_prior = float(y[nonnegative].mean()) if nonnegative.any() else self.prior
        self.new_gap_positives = int(y[nonnegative].sum())
        self.single_class = len(set(y.tolist())) < 2
        self.new_gap_single_class = len(set(y[nonnegative].tolist())) < 2
        if not self.new_gap_single_class:
            classifier = lgb.LGBMClassifier(**_params(CLASSIFIER, smoke))
            self.new_gap_classifier = classifier.fit(x[nonnegative], y[nonnegative])
            self.new_gap_logistic = _logistic().fit(x[nonnegative], y[nonnegative])
        if self.single_class:
            # Классификатор не обучается без обоих классов; честно отдаём частоту train.
            return self
        self.classifier = lgb.LGBMClassifier(**_params(CLASSIFIER, smoke)).fit(x, y)
        self.logistic = _logistic().fit(x, y)
        # Минимум остатка за горизонт в долях оборота, без обрезки; вероятность — доля распределения ниже нуля.
        lows = np.array([w.truth[:, 2].min() / scale(w) for w in windows])
        params = _params(WINDOW_REGRESSOR, smoke)
        self.lows = {a: lgb.LGBMRegressor(objective="quantile", alpha=a, **params).fit(x, lows)
                     for a in MIN_QUANTILES}
        return self

    def predict(self, windows):
        x = np.array([risk_vector(w) for w in windows], dtype=float)
        prior = np.full(len(x), self.new_gap_prior)
        if self.new_gap_single_class:
            trained = (prior, prior)
        else:
            trained = (self.new_gap_classifier.predict_proba(x)[:, 1], self.new_gap_logistic.predict_proba(x)[:, 1])
        new_gap = dict(zip(self.NEW_GAP, (*trained, prior), strict=True))
        if self.single_class:
            return {**{name: np.full(len(x), self.prior) for name in self.NAMES}, **new_gap}
        q = np.sort(np.column_stack([self.lows[a].predict(x) for a in MIN_QUANTILES]), axis=1)
        lows = np.array([np.interp(0.0, row, MIN_QUANTILES, left=0.005, right=0.995) for row in q])
        negative = x[:, 3] > 0
        return dict(zip(self.NAMES, (
            self.classifier.predict_proba(x)[:, 1],
            self.logistic.predict_proba(x)[:, 1],
            lows,
            np.full(len(x), self.prior),
            np.where(negative, *self.persistence),
        ), strict=True)) | new_gap

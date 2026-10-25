"""Явно подключаемый локальный резерв; default-реестр и production не меняются."""

import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from app.modules.contracts import ForecastPointDTO, ForecastResult, RiskSummary
from app.modules.forecasting.service import get_forecast_service
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, assess_quality, validate_input
from .features import DirectCandidate
from .uncertainty import ErrorTrajectories


class LocalFallbackService:
    """Сервис для ручной локальной проверки прошедшего validation кандидата."""

    model_version = "local-direct-cashflow-1.0"

    def __init__(self, artifacts: Path, *, allow_unreleased: bool = False):
        self.artifacts = Path(artifacts)
        self.current = get_forecast_service()
        self.candidate = None
        self.paths = None
        self.selected = None
        self.weight = 1.0
        self.allow_unreleased = allow_unreleased

    def _load(self):
        if self.candidate is not None:
            return True
        required = ["results.json", "selection-frozen.json", "residual-paths.npz", "probabilities.json"]
        if not all((self.artifacts / name).is_file() for name in required):
            return False
        release_path = self.artifacts / "release.json"
        released = release_path.is_file() and json.loads(release_path.read_text(encoding="utf-8")).get("allowed") is True
        if not released and not self.allow_unreleased:
            return False
        report = json.loads((self.artifacts / "results.json").read_text(encoding="utf-8"))
        choice = json.loads((self.artifacts / "selection-frozen.json").read_text(encoding="utf-8"))
        if choice != report["selection"] or not choice["point_validation_gate"] or choice["selected"] == "current":
            return False
        selected = choice["selected"]
        name = selected.split("_blend")[0]
        if name not in {"direct_depth4", "direct_depth6"}:
            raise ValueError("Неизвестная локальная модель")
        model_path = self.artifacts / f"{name}.cbm"
        expected = report["weights_sha256"][model_path.name]
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != expected:
            raise ValueError("Хэш локальных весов не совпадает с отчётом")
        from catboost import CatBoostRegressor
        candidate = DirectCandidate(int(name[-1]))
        candidate.model = CatBoostRegressor()
        candidate.model.load_model(str(model_path))
        with np.load(self.artifacts / "residual-paths.npz", allow_pickle=False) as archive:
            paths = ErrorTrajectories(archive["paths"])
        self.candidate, self.paths, self.selected = candidate, paths, selected
        self.weight = float(selected.split("_blend")[1]) if "_blend" in selected else 1.0
        return True

    def _fallback(self, data, reason):
        result = self.current.run(data)
        return replace(result, details={**result.details, "local_candidate": {"used": False, "reason": reason}})

    def run(self, data):
        data = validate_input(data)
        if data.planned_events or data.scenario:
            return self._fallback(data, "Планы и сценарии обслуживает текущий проверенный движок")
        if data.horizon_days > 30 or data.as_of < date(2026, 6, 30):
            return self._fallback(data, "Горизонт или дата вне проверенной области локального артефакта")
        quality = assess_quality(data)
        if quality.history_days < 28 or not quality.eligible_for_simulation:
            return self._fallback(data, "Недостаточная история либо неподтверждённый opening")
        if not self._load():
            return self._fallback(data, "Нет полного прошедшего validation артефакта")
        flows, balance, scale, _ = self.candidate.predict(data)
        if self.weight != 1:
            base = self.current.run(data)
            base_balance = np.array([point.balance_p50_minor for point in base.points])
            base_flows = np.array([[point.inflow_minor, point.outflow_minor] for point in base.points])
            balance = np.rint(self.weight * balance + (1 - self.weight) * base_balance).astype(np.int64)
            flows = np.rint(self.weight * flows + (1 - self.weight) * base_flows).astype(np.int64)
        estimate = self.paths.predict(balance, scale)
        if any(np.max(np.abs(values)) > MAX_MONEY_MINOR for values in (flows, balance, estimate["lower"], estimate["upper"])):
            return self._fallback(data, "Прогноз вышел за денежный бюджет приложения")
        available = quality.eligible_for_probability
        points = [ForecastPointDTO(data.as_of + timedelta(days=i+1), int(flows[i, 0]), int(flows[i, 1]),
                                   int(round(estimate["lower"][i])), int(balance[i]), int(round(estimate["upper"][i])),
                                   float(estimate["daily"][i]) if available else None)
                  for i in range(data.horizon_days)]
        negative = [p for p in points if p.balance_p50_minor < 0]
        warning = "Локальный эксперимент: вероятность по прошлым ошибкам не подтверждена как калиброванная."
        return ForecastResult(
            self.model_version, points,
            RiskSummary(available, negative[0].point_date if negative else None,
                        -min(p.balance_p50_minor for p in negative) if negative else None,
                        estimate["union"] if available else None),
            assumptions=["Пустые дни считаются нулевыми при допущении полной выписки.",
                         "Будущие денежные потоки предсказываются по доступному прошлому."],
            data_warnings=list(quality.warnings) + [warning],
            details={"summary": "Локальный прямой CatBoost-прогноз, не включён в production.",
                     "model": self.selected, "quality": quality.to_dict(), "paths": 200,
                     "risk_probability": {"status": "estimated_uncalibrated" if available else "unavailable",
                                          "calibrated": False, "probability_any_negative": estimate["union"] if available else None,
                                          "opening_already_negative": data.opening_balance_minor < 0, "reason": warning},
                     "local_candidate": {"used": True, "production_activated": False},
                     "explanations": [], "recurrence_ids": [],
                     "daily_components": [{"date": p.point_date.isoformat(), "irregular_in_minor": p.inflow_minor,
                                           "irregular_out_minor": p.outflow_minor, "known_in_minor": 0,
                                           "known_out_minor": 0, "planned_in_minor": 0, "planned_out_minor": 0,
                                           "recurrence_in_minor": 0, "recurrence_out_minor": 0,
                                           "scenario_expense_in_minor": 0, "scenario_expense_out_minor": 0} for p in points]})

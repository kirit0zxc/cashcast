"""Продуктовая2.0: выбранная математика1.0, строгий quality и честный риск None."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from app.modules.contracts import Direction, ForecastInput, ForecastResult, RiskSummary
from app.modules.forecasting.legacy_v1.seasonal import SeasonalForecastService
from app.modules.forecasting.v2.incremental_engine import IncrementalSeasonalService
from app.modules.forecasting.v2.incremental_state import STATE_KEY, IncrementalState
from app.modules.forecasting.v2.legacy_limits import check_legacy_cost, check_output_budget
from app.modules.forecasting.v2.quality import ForecastInputError, assess_quality, validate_input

MODEL_VERSION = "seasonal-guarded-2.0-w84"
RISK_POLICY_VERSION = "risk-policy-2.0-withheld-new-gap"


class GuardedForecastService:
    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def run(self, data: ForecastInput, *, state: dict | None = None) -> ForecastResult:
        data = validate_input(data)
        quality = assess_quality(data)
        clean = replace(
            data,
            txns=[
                replace(txn, direction=Direction(txn.direction))
                for txn in data.txns
                if not quality.reconciliation_breaks or txn.booked_on >= quality.training_start
            ],
            daily_balances=[
                balance
                for balance in data.daily_balances
                if not quality.reconciliation_breaks or balance.balance_date >= quality.training_start
            ],
            planned_events=[replace(event, direction=Direction(event.direction)) for event in data.planned_events],
        )
        prepared = IncrementalState.unpack(data, state)
        if prepared is None:
            check_legacy_cost(clean)
        # Для дельты ресурсный guard выполняется по новым группам до календаря/исключений.
        engine = IncrementalSeasonalService()
        try:
            result = (SeasonalForecastService().run(clean) if data.scenario
                      else engine.run(clean, prepared))
        except (ValueError, OverflowError) as error:
            code = "invalid_scenario" if data.scenario else "invalid_forecast_input"
            raise ForecastInputError(code, "Неподдерживаемые параметры или календарная граница расчёта") from error
        check_output_budget(result)
        points = [
            replace(
                point,
                probability_negative=None,
                balance_p10_minor=point.balance_p10_minor
                if quality.eligible_for_simulation
                else point.balance_p50_minor,
                balance_p90_minor=point.balance_p90_minor
                if quality.eligible_for_simulation
                else point.balance_p50_minor,
            )
            for point in result.points
        ]
        minimum = min(points, key=lambda point: point.balance_p50_minor)
        explanations = list(result.details["explanations"])
        sources = [
            item
            for item in explanations
            if item["kind"] in {"planned", "recurrence"}
            and item["detail"]["direction"] == "out"
            and item["detail"]["date"] <= minimum.point_date.isoformat()
        ]
        related = sorted({item["source_ref"] for item in sources if item["kind"] == "planned" and item["source_ref"]})
        negatives = [point for point in points if point.balance_p50_minor < 0]
        risk = RiskSummary(
            False,
            negatives[0].point_date if negatives else None,
            max(-point.balance_p50_minor for point in negatives) if negatives else None,
            None,
            related if negatives else [],
        )
        reasons = ["new_gap_quality_not_verified"]
        if not quality.eligible_for_probability:
            reasons.append("insufficient_reliable_history")
        if data.horizon_days != 30:
            reasons.append("horizon_not_calibrated")
        if data.scenario:
            reasons.append("scenario_not_calibrated")
        if data.planned_events:
            reasons.append("planned_events_not_calibrated")
        explanations.append(
            {
                "kind": "risk_minimum",
                "label": "Минимум медианного остатка, без вероятностной гарантии",
                "amount_minor": minimum.balance_p50_minor,
                "detail": {
                    "date": minimum.point_date.isoformat(),
                    "opening_already_negative": data.opening_balance_minor < 0,
                    "sources": [{"kind": item["kind"], "source_ref": item["source_ref"]} for item in sources],
                    "causal_guarantee": False,
                },
            }
        )
        components = []
        indexed = defaultdict(int)
        for item in explanations:
            if item["kind"] in {"planned", "recurrence", "scenario_expense"}:
                detail = item["detail"]
                indexed[detail["date"], item["kind"], detail["direction"]] += item["amount_minor"]
        for point, known in zip(points, result.details["daily_components"], strict=True):
            day = point.point_date.isoformat()
            amounts = {
                f"{kind}_{direction}_minor": indexed[day, kind, direction]
                for kind in ("planned", "recurrence", "scenario_expense")
                for direction in ("in", "out")
            }
            components.append(
                {
                    "date": day,
                    **amounts,
                    "known_in_minor": known["planned_in_minor"],
                    "known_out_minor": known["planned_out_minor"],
                    "irregular_in_minor": point.inflow_minor - known["planned_in_minor"],
                    "irregular_out_minor": point.outflow_minor - known["planned_out_minor"],
                }
            )
        details = {
            **result.details,
            "summary": "Прогноз потоков и медианного остатка; вероятность нового разрыва не подтверждена.",
            "quality": quality.to_dict(),
            "explanations": explanations,
            "daily_components": components,
            "point_method_version": "seasonal-block-bootstrap-1.0-w84",
            "risk_probability": {
                "policy_version": RISK_POLICY_VERSION,
                "status": "unavailable",
                "reasons": reasons,
                "experiment": "B6-risk-calibration-v2",
                "fit_new_gap_folds": 1,
                "check_new_gap_folds": 2,
                "scope": "Вероятность не выдаётся после аудита уже отрицательных остатков; None не означает0.",
            },
        }
        details["calculation"] = {
            "mode": "incremental" if prepared is not None else "full",
            "reason": ("planned_events_changed" if state["fingerprint"] == IncrementalState.fingerprint(data)
                       else "observed_data_changed") if prepared is not None else
                      ("scenario_requires_full" if data.scenario else "no_compatible_checkpoint"),
            "reused_history": prepared is not None,
            "bootstrap_paths_generated": result.details["paths"] if data.scenario else
                                         engine.metrics["bootstrap_paths_generated"],
        }
        if not data.scenario:
            details["calculation"].update(engine.metrics)
        if not data.scenario:
            details[STATE_KEY] = IncrementalState.pack(data, engine.prepared)
        assumptions = [value for value in result.assumptions if "вероятности модельные" not in value]
        assumptions.append(
            "Эмпирические p10/p90 не являются подтверждённым доверительным интервалом нового кассового разрыва."
        )
        warnings = list(
            dict.fromkeys(
                [
                    *result.data_warnings,
                    *quality.warnings,
                    "Вероятность нового кассового разрыва не подтверждена; None отличается от нулевого риска.",
                ]
            )
        )
        output = ForecastResult(self.model_version, points, risk, assumptions, warnings, details)
        return self.finalize_probability(result, output, quality, data)

    def finalize_probability(self, raw, output, quality, data):
        # Закреплённая версия2.0 сохраняет прежнюю политику и результаты старых заданий.
        return output

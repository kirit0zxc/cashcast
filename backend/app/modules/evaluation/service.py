"""Детерминированный backtest: будущие факты никогда не передаются ForecastService."""

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta

from app.modules.categorization.service import get_categorizer
from app.modules.contracts import DailyBalanceDTO, Direction, ForecastInput, TxnDTO
from app.modules.evaluation.metrics import EvaluationMetrics as Metrics
from app.modules.forecasting.service import get_forecast_service
from app.modules.planning.service import get_recurrence_detector


class CheckpointEvaluation:
    @staticmethod
    def fingerprint(payload):
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()

    @classmethod
    def run(cls, payload):
        config = payload["config"]
        txns = [
            TxnDTO(
                **{
                    **item,
                    "booked_on": date.fromisoformat(item["booked_on"]),
                    "direction": Direction(item["direction"]),
                }
            )
            for item in payload["transactions"]
        ]
        balances = {date.fromisoformat(item["date"]): item["balance_minor"] for item in payload["balances"]}
        service = get_forecast_service(payload["model_version"])
        first = date.fromisoformat(config["as_of"])
        horizon = config["horizon_days"]
        windows = []
        trace = [
            {
                "step": "snapshot",
                "window": None,
                "message": f"Зафиксированы {len(txns)} операций и {len(balances)} EOD. "
                f"SHA-256 нормализованного набора: {payload['dataset_sha256']}. "
                "Данные не перечитываются во время расчёта.",
            }
        ]
        for index in range(config["folds"]):
            cutoff = first + timedelta(days=index * horizon)
            label = f"Окно {index + 1}"
            trace.append(
                {
                    "step": "split",
                    "window": index + 1,
                    "message": f"{label}: история до {cutoff}; факт от {cutoff + timedelta(days=1)} "
                    f"до {cutoff + timedelta(days=horizon)} изолирован от модели.",
                }
            )
            if cutoff not in balances:
                windows.append(
                    {
                        "index": index + 1,
                        "as_of": str(cutoff),
                        "status": "skipped",
                        "reason": "Нет наблюдаемого остатка точно на дату среза",
                        "points": [],
                    }
                )
                continue
            history = [t for t in txns if t.booked_on <= cutoff]
            # Никаких сегодняшних исправлений категорий и оплаченных будущим планов.
            assignments = {a.transaction_id: a.category.value for a in get_categorizer().categorize(history)}
            history = [replace(t, category=assignments.get(t.id)) for t in history]
            recurrences = get_recurrence_detector().detect(history, cutoff)
            historical_balances = [
                DailyBalanceDTO(payload["account_id"], day, amount)
                for day, amount in sorted(balances.items())
                if day <= cutoff
            ]
            data = ForecastInput(
                account_id=payload["account_id"],
                as_of=cutoff,
                horizon_days=horizon,
                opening_balance_minor=balances[cutoff],
                seed=config["seed"],
                txns=history,
                daily_balances=historical_balances,
                planned_events=[],
                recurrences=recurrences,
            )
            trace.append(
                {
                    "step": "prepare",
                    "window": index + 1,
                    "message": f"{len(history)} прошлых операций; {len(historical_balances)} остатков; "
                    f"{len(recurrences)} регулярностей; opening={balances[cutoff]} коп. "
                    "Плановые события исключены: нет истории их изменений.",
                }
            )
            result = service.run(data)
            if result.model_version != payload["model_version"]:
                raise ValueError("evaluation_model_version_mismatch")
            quality = result.details.get("quality", {})
            trace.append(
                {
                    "step": "forecast",
                    "window": index + 1,
                    "message": f"Модель {result.model_version}; seed={config['seed']}; "
                    f"траекторий={result.details.get('paths', 0)}; "
                    f"режим={quality.get('mode', 'не указан')}; "
                    f"начало истории модели={quality.get('training_start', 'не указано')}; "
                    f"несверок в истории={quality.get('reconciliation_breaks', 'не указано')}.",
                }
            )
            window = cls.score_window(index, data, result, txns, balances, config["complete_statement"])
            windows.append(window)
            trace.append(
                {
                    "step": "score",
                    "window": index + 1,
                    "message": f"Сопоставлено {sum(p['actual_balance_minor'] is not None for p in window['points'])} "
                    f"из {horizon} дней; полнота факта={window['truth_complete']}; "
                    f"несверок={window['reconciliation_breaks']}.",
                }
            )
        points = [p for w in windows for p in w["points"]]
        valid = [p for p in points if p["actual_balance_minor"] is not None]
        threshold = config["threshold"]
        daily = [
            (int(p["actual_balance_minor"] < 0), p["probability_negative"])
            for p in valid
            if p["probability_negative"] is not None
        ]
        median = [(int(p["actual_balance_minor"] < 0), int(p["balance_p50_minor"] < 0)) for p in valid]
        horizons = [
            (int(w["actual_new_gap"]), w["probability_any_negative"])
            for w in windows
            if w.get("actual_new_gap") is not None and w.get("probability_any_negative") is not None
        ]
        regression = {
            name: Metrics.regression(
                [(p[f"actual_{field}_minor"], p[prediction]) for p in points if p[f"actual_{field}_minor"] is not None]
            )
            for name, field, prediction in (
                ("balance", "balance", "balance_p50_minor"),
                ("inflow", "inflow", "inflow_minor"),
                ("outflow", "outflow", "outflow_minor"),
            )
        }
        covered = sum(p["balance_p10_minor"] <= p["actual_balance_minor"] <= p["balance_p90_minor"] for p in valid)
        trace.append(
            {
                "step": "metrics",
                "window": None,
                "message": f"Метрики рассчитаны по факту; дней={len(valid)}, вероятностных дней={len(daily)}, "
                f"полных горизонтов нового минуса={len(horizons)}. Порог {threshold} не подбирался.",
            }
        )
        return {
            "report_version": "checkpoint-evaluation-1.0",
            "model_version": payload["model_version"],
            "account_id": payload["account_id"],
            "currency": "RUB",
            "config": config,
            "dataset_sha256": payload["dataset_sha256"],
            "source_sha256": config.get("source_sha256"),
            "source_sha256_origin": "importer_supplied_not_verified_here",
            "evaluated_scope": "statement_only_no_planned_events",
            "dataset_counts": {"transactions": len(txns), "balances": len(balances)},
            "regression": regression,
            "daily_median_negative": Metrics.classification(median, probabilities=False),
            "daily_probability_negative": Metrics.classification(daily, threshold),
            "horizon_new_gap": Metrics.classification(horizons, threshold),
            "interval_coverage": Metrics.value(covered / len(valid) if valid else None, "Нет фактических остатков"),
            "windows": windows,
            "trace": trace,
            "limitations": [
                "Вероятности — некалиброванные модельные оценки, не гарантия.",
                "Дни и окна одного счёта зависимы; метрики не доказывают перенос на другие компании.",
                "Плановые события исключены; оценка относится к прогнозу по истории операций.",
                "Отсутствующие факты не заменены нулями. "
                "Восстановление допускается только при подтверждённой полноте выписки.",
                "Accuracy при редких разрывах малоинформативна; "
                "смотрите precision, recall и число положительных случаев.",
                "Исходный уже отрицательный остаток исключён из метрик НОВОГО разрыва на горизонте.",
            ],
        }

    @staticmethod
    def score_window(index, data, result, txns, balances, complete):
        flows = defaultdict(lambda: {"in": 0, "out": 0})
        end = data.as_of + timedelta(days=data.horizon_days)
        for txn in txns:
            if data.as_of < txn.booked_on <= end:
                flows[txn.booked_on][txn.direction.value] += txn.amount_minor
        reconstructed, running, breaks = {}, data.opening_balance_minor, 0
        for offset in range(1, data.horizon_days + 1):
            day = data.as_of + timedelta(days=offset)
            running += flows[day]["in"] - flows[day]["out"]
            reconstructed[day] = running
            if day in balances and balances[day] != running:
                breaks += 1
        usable_flow = complete and breaks == 0
        points = []
        components = {item["date"]: item for item in result.details.get("daily_components", [])}
        for p in result.points:
            day = p.point_date
            actual = balances.get(day)
            observed = actual is not None
            if not observed and usable_flow:
                actual = reconstructed[day]
            points.append(
                {
                    "date": str(day),
                    "inflow_minor": p.inflow_minor,
                    "outflow_minor": p.outflow_minor,
                    "balance_p10_minor": p.balance_p10_minor,
                    "balance_p50_minor": p.balance_p50_minor,
                    "balance_p90_minor": p.balance_p90_minor,
                    "probability_negative": p.probability_negative,
                    "actual_balance_minor": actual,
                    "balance_source": "observed" if observed else "reconstructed" if usable_flow else "missing",
                    "actual_inflow_minor": flows[day]["in"] if usable_flow else None,
                    "actual_outflow_minor": flows[day]["out"] if usable_flow else None,
                    # Только числовые компоненты; никакого текста платежей/контрагентов.
                    "components": {
                        key: value
                        for key, value in components.get(str(day), {}).items()
                        if key.endswith("_minor") and isinstance(value, int)
                    },
                }
            )
        full = len(points) == data.horizon_days and all(p["actual_balance_minor"] is not None for p in points)
        actual_new_gap = (
            any(p["actual_balance_minor"] < 0 for p in points) if full and data.opening_balance_minor >= 0 else None
        )
        warnings = list(result.data_warnings)
        if not complete:
            warnings.append("Полнота выписки не подтверждена: ошибки потоков не считаются.")
        if breaks:
            warnings.append("Обнаружена несверка остатков: восстановление EOD и оценка потоков отключены.")
        return {
            "index": index + 1,
            "as_of": str(data.as_of),
            "status": "succeeded",
            "opening_balance_minor": data.opening_balance_minor,
            "points": points,
            "truth_complete": full,
            "reconciliation_breaks": breaks,
            "actual_new_gap": actual_new_gap,
            "probability_any_negative": result.risk.probability_any_negative,
            "warnings": warnings,
        }


def handle_evaluation(_session, payload):
    # Отдельный обработчик очереди: не читает финансовые таблицы во время расчёта.
    return CheckpointEvaluation.run(payload)

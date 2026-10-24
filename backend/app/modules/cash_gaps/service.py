"""Детерминированная карточка: факты и допущения отделены от вероятности."""

from app.api.schemas.cash_gaps import CashGapPreview, GapFunding, GapSummary
from app.core.errors import AppError
from app.modules.forecasting.v2.quality import validate_input
from app.modules.pulse.frozen import FrozenPulseService


class CashGapService:
    @staticmethod
    def summarize(days, balances, *, reliable: bool) -> GapSummary:
        episodes = []
        start = None
        for i, balance in enumerate([*balances, 0]):
            if balance < 0 and start is None:
                start = i
            if balance >= 0 and start is not None:
                worst = min(range(start, i), key=lambda n: balances[n])
                episodes.append(
                    {
                        "kind": "existing" if start == 0 else "new",
                        "first_negative_date": days[start],
                        "last_negative_date": days[i - 1],
                        "recovery_date": days[i] if i < len(days) else None,
                        "observed_days": i - start,
                        # Истинное начало текущего минуса и продолжение за горизонтом неизвестны.
                        "duration_is_lower_bound": start == 0 or i == len(days),
                        "max_deficit_minor": -balances[worst],
                        "worst_date": days[worst],
                    }
                )
                start = None
        return GapSummary(
            status="gap" if episodes else "no_gap" if reliable else "insufficient_data",
            opening_already_negative=balances[0] < 0,
            first_new_gap_date=next((e["first_negative_date"] for e in episodes if e["kind"] == "new"), None),
            max_deficit_minor=max(0, -min(balances)),
            total_negative_days=sum(e["observed_days"] for e in episodes),
            episodes=episodes,
        )

    @classmethod
    def build(cls, data, points, details, *, company_id, preview: CashGapPreview | None = None):
        data = validate_input(data)
        curve = FrozenPulseService.curve(data, points, details, company_id)
        days = [data.as_of, *curve.days]
        base = [data.opening_balance_minor, *[p.balance_p50_minor for p in points]]
        changed = base.copy()
        quality = details.get("quality", {})
        reliable = quality.get("eligible_for_simulation") is True
        choices = []
        evidence = {}
        explanations = details.get("explanations", [])
        plans = {p.id: p for p in data.planned_events}
        for flow in curve.flows:
            if not flow.ref.startswith("known:"):
                evidence[flow.ref] = ("estimated", None)
                continue
            item = explanations[int(flow.ref.split(":")[1])]
            ref = item.get("source_ref")
            kind = (
                "planned" if flow.kind == "planned" else "scenario" if flow.kind == "scenario_expense" else "estimated"
            )
            evidence[flow.ref] = (kind, ref)
            plan = plans.get(ref)
            # Нельзя переносить налог/зарплату/кредит/аренду или неизвестный расход.
            flexible = flow.flexibility == "flexible" or (
                flow.kind == "planned" and plan is not None and plan.category == "purchases" and plan.kind != "tax"
            )
            choices.append(
                {
                    "id": flow.ref,
                    "source_ref": ref,
                    "date": flow.day,
                    "amount_minor": flow.amount_minor,
                    "label": flow.label,
                    "evidence": kind,
                    "delay_allowed": flow.amount_minor > 0 or flexible,
                }
            )
        warnings = [
            "Разрыв определяется по медиане остатка на конец дня; внутридневной дефицит не оценён.",
            "Причины — состав расчёта до минимума, а не доказанная причинная связь. Планы ещё не являются оплатами.",
            "Проверка действий не изменяет платежи и прогноз. Допущения требуют проверки и согласования.",
        ]
        if not reliable:
            warnings.append(
                "Истории недостаточно для надёжной симуляции: отсутствие минуса не доказывает отсутствие риска."
            )
        debt = cost = 0
        selected = set()
        for action in preview.actions if preview else []:
            if isinstance(action, GapFunding):
                if not data.as_of < action.date <= days[-1] or action.repayment_date <= action.date:
                    raise AppError(
                        422, "invalid_financing_dates", "Получение — внутри горизонта, возврат — позже получения"
                    )
                cost += action.cost_minor
                if action.repayment_date > days[-1]:
                    debt += action.amount_minor + action.cost_minor
                for i, day in enumerate(days):
                    changed[i] += action.amount_minor if day >= action.date else 0
                    changed[i] -= action.amount_minor + action.cost_minor if day >= action.repayment_date else 0
            else:
                flow = next((f for f in choices if f["id"] == action.flow_id), None)
                if flow is None or not flow["delay_allowed"] or action.flow_id in selected:
                    raise AppError(422, "invalid_gap_flow", "Поток недоступен для переноса или выбран повторно")
                if not flow["date"] < action.to_date <= days[-1]:
                    raise AppError(422, "invalid_delay_date", "Перенос возможен только вперёд в пределах горизонта")
                if flow["amount_minor"] < 0 and not action.payment_delay_agreed:
                    raise AppError(422, "payment_delay_not_agreed", "Подтвердите допустимость гипотезы отсрочки")
                selected.add(action.flow_id)
                for i, day in enumerate(days):
                    if flow["date"] <= day < action.to_date:
                        changed[i] -= flow["amount_minor"]
        if debt:
            warnings.append(
                "После горизонта остаётся долг с указанной стоимостью; устранение дефицита после возврата не проверено."
            )
        worst = min(range(len(base)), key=lambda i: base[i])
        # При пропущенном EOD snapshot может восстановить остаток из более раннего
        # баланса или принять ноль. Такой вход нельзя называть наблюдённым фактом.
        observed_opening = any(
            b.balance_date == data.as_of and b.closing_balance_minor == data.opening_balance_minor
            for b in data.daily_balances
        )
        causes = [
            {
                "date": data.as_of,
                "amount_minor": base[0],
                "label": "Остаток на дату среза" if observed_opening else "Расчётный начальный остаток",
                "evidence": "observed" if observed_opening else "estimated",
                "source_ref": None,
            }
        ]
        for flow in curve.flows:
            if flow.day <= days[worst] and flow.amount_minor:
                kind, ref = evidence[flow.ref]
                causes.append(
                    {
                        "date": flow.day,
                        "amount_minor": flow.amount_minor,
                        "label": flow.label,
                        "evidence": kind,
                        "source_ref": ref,
                    }
                )
        original = cls.summarize(days, base, reliable=reliable)
        hypothetical = cls.summarize(days, changed, reliable=reliable)
        result = {
            "as_of": data.as_of,
            "horizon_end": days[-1],
            "base": original.model_dump(),
            "preview": hypothetical.model_dump(),
            "points": [
                {"date": d, "base_minor": b, "preview_minor": c, "delta_minor": c - b}
                for d, b, c in zip(days, base, changed, strict=True)
            ],
            "flows": choices,
            "causes": causes,
            "causes_date": days[worst],
            "causes_balance_minor": base[worst],
            "probability_reason": (
                "Проверка B6: качество вероятности нового разрыва не подтверждено; null не означает 0%."
            ),
            "quality_mode": quality.get("mode", "unknown"),
            "improvement_minor": original.max_deficit_minor - hypothetical.max_deficit_minor,
            "financing_cost_minor": cost,
            "debt_beyond_horizon_minor": debt,
            "warnings": warnings,
        }
        FrozenPulseService.check_numbers(result)
        return result

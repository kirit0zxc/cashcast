"""Пульс использует сохранённый прогноз: та же база, планы и начальный остаток."""

from datetime import timedelta

from app.core.errors import AppError
from app.modules.contracts import Category, ForecastInput
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, assess_quality, validate_input

from .adapters import operations_from_records
from .advisor.baseline_curve import BaseCurve, Flow
from .service import PulseConfig, build_pulse


class FrozenPulseService:
    VERSION = "pulse-cashcast-1.0"
    MAX_TRANSACTIONS = 10_000

    @classmethod
    def build(
        cls,
        data: ForecastInput,
        points,
        details: dict,
        *,
        company_id: str,
        buffer_minor: int | None = None,
        warnings: list[str] | None = None,
    ) -> dict:
        data = validate_input(data)
        if len(data.txns) > cls.MAX_TRANSACTIONS:
            raise AppError(422, "pulse_resource_limit", "Пульс поддерживает до10000 операций в сохранённом снимке")
        if buffer_minor is not None and (type(buffer_minor) is not int or not 0 <= buffer_minor <= MAX_MONEY_MINOR):
            raise AppError(422, "invalid_buffer", "Подушка должна быть целой неотрицательной суммой в копейках")
        curve = cls.curve(data, points, details, company_id)
        curve.warnings.extend(warnings or [])
        curve.warnings.append("Действия — гипотезы, а не изменение платежей. Сроки переноса согласуйте с контрагентом.")
        curve.warnings.append(
            "За пределами сохранённого горизонта эффект не оценён; вероятность разрыва не подтверждена."
        )
        curve.assumptions.extend(
            [
                "База повторяет медиану сохранённого прогноза CashCast; остаточный статистический поток — оценка.",
                "Стресс по клиентам изменяет оценочные поступления пропорционально исторической доле; "
                "не конкретный счёт.",
                "Ставка финансирования 20% — иллюстративная настройка, не тариф и не одобрение банка.",
            ]
        )
        operations = operations_from_records(company_id, data.txns, data.daily_balances)
        report = build_pulse(
            operations,
            company_id,
            data.as_of,
            buffer_minor=buffer_minor,
            curve=curve,
            ledger=True,
            balances={b.balance_date: b.closing_balance_minor for b in data.daily_balances},
            cash_available=bool(data.opening_balance_minor)
            or any(t.booked_on <= data.as_of for t in data.txns)
            or any(b.balance_date <= data.as_of for b in data.daily_balances)
            or any(f.kind in {"planned", "recurrence", "scenario_expense"} and f.amount_minor for f in curve.flows),
            # Вероятность может быть недоступна и при пригодной точечной модели.
            # Для старых сохранённых результатов без quality проверяем их frozen-вход.
            cash_reliable=(details["quality"]["eligible_for_simulation"] is True
                           if "eligible_for_simulation" in details.get("quality", {})
                           else assess_quality(data).eligible_for_simulation),
            cfg=PulseConfig(warn_days=data.horizon_days),
        ).to_dict()
        report["method_version"] = cls.VERSION
        cls.check_numbers(report)
        return report

    @staticmethod
    def curve(data: ForecastInput, points, details: dict, company_id: str) -> BaseCurve:
        if len(points) != data.horizon_days:
            raise AppError(409, "pulse_source_unavailable", "Неполный сохранённый ряд прогноза")
        curve = BaseCurve(company_id, data.as_of, data.opening_balance_minor, data.horizon_days)
        by_day: dict = {}
        groups = {g.group_id: g for g in data.recurrences}
        for i, item in enumerate(details.get("explanations", [])):
            if item.get("kind") not in {"planned", "recurrence", "scenario_expense"}:
                continue
            detail = item.get("detail", {})
            amount = item.get("amount_minor")
            if type(amount) is not int or amount < 0 or detail.get("direction") not in {"in", "out"}:
                raise AppError(409, "pulse_source_unavailable", "Неполные компоненты сохранённого прогноза")
            by_day.setdefault(detail.get("date"), []).append((i, item))
        previous = data.opening_balance_minor
        for i, point in enumerate(points):
            day = data.as_of + timedelta(days=i + 1)
            if point.point_date != day:
                raise AppError(409, "pulse_source_unavailable", "Непоследовательные даты сохранённого прогноза")
            known = 0
            known_in = 0
            known_out = 0
            for index, item in by_day.get(day.isoformat(), []):
                direction = item["detail"]["direction"]
                amount = item["amount_minor"] * (1 if direction == "in" else -1)
                group = groups.get(item.get("source_ref"))
                # Только распознанная закупка допускает гипотетическую отсрочку.
                # Ручной план без категории не становится поставщиком по догадке.
                flexible = (
                    item["kind"] == "recurrence"
                    and direction == "out"
                    and group is not None
                    and group.category == Category.PURCHASES
                )
                curve.flows.append(
                    Flow(
                        f"known:{index}",
                        day,
                        amount,
                        item["kind"],
                        "inflow" if direction == "in" else "flexible" if flexible else "hard",
                        item["label"],
                        "frozen",
                    )
                )
                known += amount
                known_in += max(amount, 0)
                known_out += max(-amount, 0)
            # Приход и расход сохраняются отдельно: нулевой чистый поток не означает
            # отсутствие выручки. Стресс уменьшает приход, а не сальдо дня.
            incoming = point.inflow_minor - known_in
            outgoing = point.outflow_minor - known_out
            if incoming < 0 or outgoing < 0:
                raise AppError(409, "pulse_source_unavailable", "Компоненты превышают сохранённые потоки")
            curve.flows.extend(
                [
                    Flow(f"income:{i}", day, incoming, "statistical", "inflow", "Оценочные поступления", "frozen"),
                    Flow(f"expense:{i}", day, -outgoing, "statistical", "hard", "Оценочные расходы", "frozen"),
                ]
            )
            # Медиана суммы не обязана совпадать с суммой медиан потоков.
            # Разница остаётся явно оценочным компонентом; обязательства не удваиваются.
            residual = point.balance_p50_minor - previous - known - incoming + outgoing
            curve.flows.append(
                Flow(
                    f"residual:{i}",
                    day,
                    residual,
                    "statistical",
                    "hard",
                    "Поправка к медиане (не выручка)",
                    "frozen",
                )
            )
            previous = point.balance_p50_minor
        return curve

    @classmethod
    def check_numbers(cls, value):
        if isinstance(value, dict):
            for item in value.values():
                cls.check_numbers(item)
        elif isinstance(value, list):
            for item in value:
                cls.check_numbers(item)
        elif type(value) is int and abs(value) > MAX_MONEY_MINOR:
            raise AppError(422, "pulse_money_limit", "Расчёт пульса превышает безопасный диапазон сумм")

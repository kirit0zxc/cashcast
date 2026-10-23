"""Ресурсный guard для замороженного1.0 без изменения его математики."""

from dataclasses import replace

from app.modules.contracts import ForecastInput, ForecastResult
from app.modules.forecasting.legacy_v1.categorization import get_categorizer
from app.modules.forecasting.legacy_v1.recurrence import CalendarRecurrenceDetector
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR, ForecastInputError

MAX_LEGACY_WORK = 5_000_000


def check_output_budget(result: ForecastResult) -> None:
    for point in result.points:
        amounts = (
            point.inflow_minor,
            point.outflow_minor,
            point.balance_p10_minor,
            point.balance_p50_minor,
            point.balance_p90_minor,
        )
        if any(type(amount) is not int or abs(amount) > MAX_MONEY_MINOR for amount in amounts):
            raise ForecastInputError("forecast_resource_limit", "Результат превышает поддерживаемый денежный диапазон")


def check_legacy_cost(data: ForecastInput) -> None:
    history_work = len(data.daily_balances) * len({txn.booked_on for txn in data.txns})
    if history_work > MAX_LEGACY_WORK:
        raise ForecastInputError("forecast_resource_limit", "Превышен бюджет исторической сверки закреплённой модели")
    assignments = get_categorizer().categorize(data.txns)
    txns = [
        replace(txn, category=assignment.category.value) for txn, assignment in zip(data.txns, assignments, strict=True)
    ]
    groups = CalendarRecurrenceDetector().detect(txns, data.as_of)
    member_count = sum(len(group.member_transaction_ids) for group in groups)
    # В frozen1.0 list-membership и member scans сохранены для точной воспроизводимости.
    # Ограничиваем их реальную стоимость до вызова, включая split members и occurrences.
    work = history_work + len(txns) * (member_count + len(groups))
    work += len(data.planned_events) * (data.horizon_days // 7 + 2) * member_count
    if len(groups) > 500 or work > MAX_LEGACY_WORK:
        raise ForecastInputError("forecast_resource_limit", "Превышен бюджет регулярностей закреплённой модели")

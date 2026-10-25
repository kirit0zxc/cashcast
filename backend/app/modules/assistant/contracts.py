"""Закрытый список инструментов: модель выбирает только существующие операции сайта."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.models import PlannedEventIn, PlannedEventPatch, ScenarioRequest, TransactionCategoryPatch
from app.modules.forecasting.v2.quality import MAX_MONEY_MINOR


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageArgs(Arguments):
    cursor: str | None = Field(default=None, max_length=1024)


class TransactionsArgs(PageArgs):
    date_from: date | None = None
    date_to: date | None = None
    category: str | None = Field(default=None, max_length=50)
    direction: Literal["in", "out"] | None = None


class ForecastId(Arguments):
    forecast_id: uuid.UUID


class PulseArgs(ForecastId):
    buffer_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR, strict=True)


class AsOfArgs(Arguments):
    as_of: date = Field(ge=date(2, 1, 2))


class ForecastArgs(AsOfArgs):
    horizon_days: int = Field(default=30, ge=1, le=180, strict=True)


class ScenarioArgs(ForecastId):
    body: ScenarioRequest


class CreatePlanArgs(Arguments):
    body: PlannedEventIn


class UpdatePlanArgs(Arguments):
    event_id: uuid.UUID
    body: PlannedEventPatch


class CategoryArgs(Arguments):
    transaction_id: uuid.UUID
    body: TransactionCategoryPatch


class MatchArgs(Arguments):
    planned_event_id: uuid.UUID
    transaction_id: uuid.UUID
    matched_amount_minor: int = Field(gt=0, le=MAX_MONEY_MINOR, strict=True)


class CommitArgs(Arguments):
    import_id: uuid.UUID
    import_kind: Literal["statement", "obligations"]


READS = {
    "list_transactions": (TransactionsArgs, "Операции счёта, страница 50 строк, next_cursor для продолжения."),
    "summarize_transactions": (TransactionsArgs, "Точные суммы по категориям за период, весь выбранный период."),
    "list_plans": (Arguments, "Плановые платежи выбранного счёта, до 200 строк."),
    "list_forecasts": (PageArgs, "История расчётов выбранного счёта, сначала новые."),
    "show_forecast": (ForecastId, "Показать настоящий график и таблицу сохранённого прогноза."),
    "show_explanations": (ForecastId, "Причины риска и идентификаторы источников из сохранённого прогноза."),
    "show_pulse": (PulseArgs, "Рекомендации, подушка, расходы, концентрация клиентов и эффект действий."),
    "show_comparison": (ForecastId, "График и таблица: сохранённый сценарий против своей базы."),
    "show_plan_fact": (AsOfArgs, "Просмотр обязательств, оплат и предложений сверки без изменений."),
}
WRITES = {
    "propose_forecast": (ForecastArgs, "Предложить прогноз. После подтверждения также сверяет однозначные оплаты."),
    "propose_scenario": (ScenarioArgs, "Предложить расчёт сценария от базы; реальные платежи не изменяются."),
    "propose_create_plan": (CreatePlanArgs, "Предложить новый плановый платёж. Суммы только в целых копейках."),
    "propose_update_plan": (UpdatePlanArgs, "Предложить изменение даты/суммы или отмену существующего плана."),
    "propose_category": (CategoryArgs, "Предложить ручное изменение категории банковской операции."),
    "propose_reconcile": (AsOfArgs, "Предложить применение однозначных совпадений план-факт."),
    "propose_match": (MatchArgs, "Предложить подтверждение конкретной оплаты с точной суммой."),
    "propose_commit_import": (CommitArgs, "Предложить принять уже загруженный и проверенный CSV."),
}


def tool_definitions(can_write: bool) -> list[dict]:
    # JSON Schema раскрывается локально, чтобы провайдер не интерпретировал внешние ссылки.
    def expand(value, definitions):
        if isinstance(value, list):
            return [expand(item, definitions) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]], definitions)
            return {k: expand(v, definitions) for k, v in value.items() if k != "$defs"}
        return value

    entries = {**READS, **(WRITES if can_write else {})}
    result = []
    for name, (schema, description) in entries.items():
        raw = schema.model_json_schema()
        result.append({"type": "function", "function": {
            "name": name, "description": description,
            "parameters": expand(raw, raw.get("$defs", {})),
        }})
    return result

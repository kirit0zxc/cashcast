"""Адаптер к тем же обработчикам, что использует кабинет; произвольных SQL/URL у модели нет."""

import hashlib
import json

from fastapi import Response
from sqlalchemy import func, select

from app.api.schemas.models import ForecastRequest
from app.api.schemas.plan_fact import PlanFactConfirmRequest
from app.api.v1 import comparisons, forecast_history, forecasts, imports, obligations, plan_fact, planned_events, pulse
from app.api.v1 import transactions as transaction_api
from app.core.company_access import CompanyAccess
from app.core.errors import AppError
from app.core.models import (
    Account,
    BankTransaction,
    DailyBalance,
    ForecastRun,
    ObligationImport,
    PlannedEvent,
    PlannedEventMatch,
    StatementImport,
)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


class SiteGateway:
    def __init__(self, session, user, company_id, account_id, settings):
        self.session, self.user, self.settings = session, user, settings
        self.company_id, self.account_id = company_id, account_id
        self.private_values = set()
        CompanyAccess(session).require(user.id, company_id)
        account = session.get(Account, account_id)
        if account is None or account.company_id != company_id:
            raise AppError(404, "not_found", "Счёт не найден")

    def owned(self, model, object_id):
        row = self.session.get(model, object_id)
        if row is None or row.company_id != self.company_id or row.account_id != self.account_id:
            raise AppError(404, "not_found", "Объект выбранного счёта не найден")
        return row

    def remember_private_values(self, node):
        if isinstance(node, list):
            for item in node:
                self.remember_private_values(item)
        elif isinstance(node, dict):
            for key, item in node.items():
                if key in {"counterparty_name", "counterparty_ref", "purpose"} and isinstance(item, str) and item:
                    self.private_values.add(item)
                self.remember_private_values(item)

    def fingerprint(self) -> str:
        # Согласование действительно только для показанного состояния счёта.
        # Тонкие строки без назначений/файлов; предел защищает от неограниченного чтения.
        fields = [
            (BankTransaction, ["id", "amount_minor", "booked_on", "direction", "category", "category_source"]),
            (DailyBalance, ["id", "balance_date", "closing_balance_minor"]),
            (PlannedEvent, ["id", "due_date", "amount_minor", "remaining_amount_minor", "status", "direction"]),
        ]
        state = []
        for model, names in fields:
            rows = self.session.execute(select(*(getattr(model, n) for n in names)).where(
                model.account_id == self.account_id,
            ).order_by(model.id).limit(20001)).all()
            if len(rows) > 20000:
                raise AppError(422, "assistant_account_limit", "Для действий в чате поддерживается до 20 000 записей")
            state.append([tuple(row) for row in rows])
        links = self.session.execute(select(
            PlannedEventMatch.planned_event_id, PlannedEventMatch.transaction_id,
            PlannedEventMatch.matched_amount_minor,
        ).join(PlannedEvent, PlannedEvent.id == PlannedEventMatch.planned_event_id).where(
            PlannedEvent.account_id == self.account_id,
        ).order_by(PlannedEventMatch.planned_event_id, PlannedEventMatch.transaction_id).limit(20001)).all()
        if len(links) > 20000:
            raise AppError(422, "assistant_account_limit", "Слишком много связей для подтверждения в чате")
        state.append([tuple(row) for row in links])
        return digest(state)

    def validate_target(self, name, args):
        if hasattr(args, "forecast_id"):
            self.owned(ForecastRun, args.forecast_id)
        if hasattr(args, "event_id"):
            self.owned(PlannedEvent, args.event_id)
        if hasattr(args, "planned_event_id"):
            self.owned(PlannedEvent, args.planned_event_id)
        if hasattr(args, "transaction_id"):
            self.owned(BankTransaction, args.transaction_id)
        if hasattr(args, "import_id"):
            self.owned(StatementImport if args.import_kind == "statement" else ObligationImport, args.import_id)
        if name == "propose_create_plan":
            if args.body.account_id not in {None, self.account_id}:
                raise AppError(404, "not_found", "Счёт не найден")
            args.body.account_id = self.account_id
            if args.body.description and len(args.body.description) > 1000:
                raise AppError(422, "invalid_tool_arguments", "Описание плана слишком длинное")

    def read(self, name, args) -> tuple[dict, dict]:
        self.validate_target(name, args)
        if name == "show_pulse":
            # В текстах стресса встречаются и клиенты, не вошедшие в top/at_risk.
            # Полный словарь исходников остаётся локально; наружу уходят только псевдонимы.
            snapshot = self.owned(ForecastRun, args.forecast_id).input_snapshot or {}
            self.remember_private_values(snapshot)
        common = {"session": self.session, "user": self.user}
        company = {"company_id": self.company_id, "_company": str(self.company_id), "session": self.session}
        kind, title = "table", name
        if name == "list_transactions":
            result = transaction_api.list_transactions(account_id=self.account_id, limit=50, **company,
                                                       **args.model_dump()).model_dump(mode="json")
            title = "Банковские операции"
        elif name == "summarize_transactions":
            stmt = select(BankTransaction.category, BankTransaction.direction,
                          func.sum(BankTransaction.amount_minor), func.count()).where(
                BankTransaction.account_id == self.account_id, BankTransaction.company_id == self.company_id)
            for key, op in (("date_from", "ge"), ("date_to", "le")):
                value = getattr(args, key)
                if value:
                    stmt = stmt.where(BankTransaction.booked_on >= value if op == "ge"
                                      else BankTransaction.booked_on <= value)
            if args.category:
                stmt = stmt.where(BankTransaction.category == args.category)
            if args.direction:
                stmt = stmt.where(BankTransaction.direction == args.direction)
            rows = self.session.execute(stmt.group_by(BankTransaction.category, BankTransaction.direction)).all()
            result = {"items": [{"category": c, "direction": d, "amount_minor": int(s), "count": n}
                                for c, d, s, n in rows], "complete": True}
            title = "Суммы по категориям"
        elif name == "list_plans":
            rows = self.session.scalars(select(PlannedEvent).where(
                PlannedEvent.company_id == self.company_id, PlannedEvent.account_id == self.account_id,
            ).order_by(PlannedEvent.due_date, PlannedEvent.id).limit(201)).all()
            result = {"items": [planned_events._to_out(r).model_dump(mode="json") for r in rows[:200]],
                      "truncated": len(rows) > 200}
            title = "Плановые платежи"
        elif name == "list_forecasts":
            result = forecast_history.list_forecast_history(account_id=self.account_id, limit=20,
                       cursor=args.cursor, **company).model_dump(mode="json")
            title = "История прогнозов"
        elif name == "show_plan_fact":
            result = plan_fact.plan_fact(
                account_id=self.account_id, as_of=args.as_of, **company).model_dump(mode="json")
            title = "План и факт"
        else:
            readers = {"show_forecast": forecasts.get_forecast, "show_explanations": forecasts.get_explanations,
                       "show_pulse": pulse.get_pulse, "show_comparison": comparisons.compare_forecasts}
            result = readers[name](**args.model_dump(), **common).model_dump(mode="json")
            kind = {"show_forecast": "forecast", "show_comparison": "comparison", "show_pulse": "pulse"}.get(
                name, "table")
            title = {"show_forecast": "Прогноз остатка", "show_comparison": "Сравнение сценария",
                     "show_pulse": "Финансовый пульс", "show_explanations": "Причины риска"}[name]
        card = {"kind": kind, "title": title, "data": result}
        return result, card

    def execute(self, name, args) -> dict:
        # Метод вызывается только подтверждением пользователя, не циклом model tools.
        CompanyAccess(self.session).require(self.user.id, self.company_id, write=True)
        self.validate_target(name, args)
        common = {"session": self.session, "user": self.user}
        company = {"company_id": self.company_id, "_company": str(self.company_id), "session": self.session}
        if name == "propose_create_plan":
            result = planned_events.create_event(body=args.body, user=self.user, **company)
        elif name == "propose_update_plan":
            result = planned_events.patch_event(event_id=args.event_id, body=args.body, **common)
        elif name == "propose_category":
            result = transaction_api.patch_category(transaction_id=args.transaction_id, body=args.body, **common)
        elif name == "propose_forecast":
            result = forecasts.create_forecast(body=ForecastRequest(account_id=self.account_id, **args.model_dump()),
                     response=Response(), user=self.user, settings=self.settings, **company)
        elif name == "propose_scenario":
            result = forecasts.create_scenario(forecast_id=args.forecast_id, body=args.body, response=Response(),
                                               settings=self.settings, **common)
        elif name == "propose_reconcile":
            result = plan_fact.reconcile(account_id=self.account_id, as_of=args.as_of, **company)
        elif name == "propose_match":
            result = plan_fact.confirm_proposal(body=PlanFactConfirmRequest(account_id=self.account_id,
                                                  **args.model_dump()), **company)
        elif name == "propose_commit_import":
            handler = imports.commit_import if args.import_kind == "statement" else obligations.commit_obligations
            result = handler(import_id=args.import_id, **common)
        else:
            raise AppError(422, "unknown_tool", "Неизвестное действие")
        return result.model_dump(mode="json")

"""Двухфазные действия: предложение неизменно, повтор подтверждения не повторяет изменение."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.company_access import CompanyAccess
from app.core.errors import AppError
from app.core.models import Account, AssistantAction
from app.modules.assistant.contracts import WRITES

TITLES = {
    "propose_forecast": "Рассчитать прогноз и сверить однозначные оплаты",
    "propose_scenario": "Рассчитать сценарий по сохранённой базе",
    "propose_create_plan": "Создать плановый платёж",
    "propose_update_plan": "Изменить плановый платёж",
    "propose_category": "Изменить категорию операции",
    "propose_reconcile": "Применить сверку план-факт",
    "propose_match": "Подтвердить связь оплаты и обязательства",
    "propose_commit_import": "Принять операции из проверенного CSV",
}


class ActionService:
    def __init__(self, gateway):
        self.gateway, self.session = gateway, gateway.session

    def propose(self, name, arguments) -> dict:
        g = self.gateway
        CompanyAccess(self.session).require(g.user.id, g.company_id, write=True)
        args = WRITES[name][0].model_validate(arguments)
        g.validate_target(name, args)
        action = AssistantAction(user_id=uuid.UUID(g.user.id), company_id=g.company_id, account_id=g.account_id,
                                 name=name, arguments=args.model_dump(mode="json"), fingerprint=g.fingerprint(),
                                 expires_at=datetime.now(UTC) + timedelta(minutes=15))
        self.session.add(action)
        self.session.flush()
        return self.card(action)

    @staticmethod
    def card(action) -> dict:
        return {"kind": "action", "title": TITLES[action.name], "data": {
            "action_id": str(action.id), "name": action.name, "arguments": action.arguments,
            "status": action.status, "expires_at": action.expires_at.isoformat(),
            "account_id": str(action.account_id),
        }}

    def decide(self, action_id, decision) -> dict:
        g = self.gateway
        action = self.session.scalar(select(AssistantAction).where(
            AssistantAction.id == action_id, AssistantAction.user_id == uuid.UUID(g.user.id),
            AssistantAction.company_id == g.company_id, AssistantAction.account_id == g.account_id,
        ).with_for_update())
        if action is None:
            raise AppError(404, "not_found", "Предложение не найдено")
        CompanyAccess(self.session).require(g.user.id, g.company_id, write=True)
        if action.status == "confirmed":
            return action.result
        if action.status == "cancelled":
            return {"text": "Предложение отменено. Данные не изменены.", "cards": [self.card(action)]}
        if decision == "cancel":
            action.status = "cancelled"
            return {"text": "Предложение отменено. Данные не изменены.", "cards": [self.card(action)]}
        if action.expires_at <= datetime.now(UTC):
            raise AppError(409, "assistant_action_expired", "Предложение истекло. Запросите новое")
        # Общая с импортом/правкой/сверкой блокировка защищает проверку до commit.
        self.session.scalar(select(Account.id).where(Account.id == g.account_id).with_for_update())
        if g.fingerprint() != action.fingerprint:
            raise AppError(409, "assistant_action_stale", "Данные счёта изменились. Запросите новое предложение")
        result = g.execute(action.name, WRITES[action.name][0].model_validate(action.arguments))
        action.status = "confirmed"
        card = {"kind": "job" if "job_id" in result else "table", "title": "Результат подтверждённого действия",
                "data": result}
        action.result = {"text": "Действие подтверждено и принято сервером.", "cards": [self.card(action), card]}
        self.session.flush()
        return action.result

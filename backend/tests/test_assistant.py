"""Реальные HTTP/БД границы ассистента; внешний платный провайдер заменён детерминированным ответом."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import AssistantAction, AssistantTurn, BankTransaction, Company, CompanyMember, PlannedEvent
from app.modules.assistant.provider import OpenRouterClient
from app.modules.assistant.service import ModelProjection
from tests.factories import make_account, make_company, make_user
from tests.test_integration import _MAPPING, PASSWORD, _run_worker_until_idle, _statement_csv
from tests.test_integration import logged_in as login_fixture


@pytest.fixture
def logged_in(client, session_factory):
    return login_fixture.__wrapped__(client, session_factory)


def chat_url(ctx):
    return f"/api/v1/companies/{ctx['company_id']}/assistant/chat"


def action_url(ctx, action_id):
    return (f"/api/v1/companies/{ctx['company_id']}/accounts/{ctx['account_id']}"
            f"/assistant/actions/{action_id}")


def request(ctx):
    return {"request_id": str(uuid.uuid4()), "account_id": ctx["account_id"], "as_of": "2026-10-24",
            "messages": [{"role": "user", "content": "Создай плановый расход 123 рубля"}]}


def mock_tools(monkeypatch, calls, final_text="Проверьте карточку и подтвердите действие."):
    seen = []

    def complete(self, messages, tools, timeout):
        seen.append(json.loads(json.dumps(messages)))
        if len(seen) == 1:
            return {"role": "assistant", "tool_calls": [{"id": f"call_{i}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(calls)]}
        return {"role": "assistant", "content": final_text}

    monkeypatch.setattr(OpenRouterClient, "complete", complete)
    return seen


def propose(client, ctx, monkeypatch):
    mock_tools(monkeypatch, [("propose_create_plan", {"body": {
        "direction": "out", "amount_minor": 12300, "due_date": "2026-11-01"}})])
    response = client.post(chat_url(ctx), json=request(ctx))
    assert response.status_code == 200, response.text
    return response.json()["cards"][0]["data"]["action_id"]


def count(session_factory, model):
    with session_factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_proposal_confirm_idempotency(client, session_factory, logged_in, monkeypatch):
    action = propose(client, logged_in, monkeypatch)
    assert count(session_factory, PlannedEvent) == 0
    path = action_url(logged_in, action)
    first = client.post(path, json={"decision": "confirm"})
    assert first.status_code == 200, first.text
    assert count(session_factory, PlannedEvent) == 1
    assert client.post(path, json={"decision": "confirm"}).json() == first.json()
    assert count(session_factory, PlannedEvent) == 1


def test_cancel_is_terminal(client, session_factory, logged_in, monkeypatch):
    path = action_url(logged_in, propose(client, logged_in, monkeypatch))
    assert client.post(path, json={"decision": "cancel"}).status_code == 200
    reply = client.post(path, json={"decision": "confirm"})
    assert reply.json()["cards"][0]["data"]["status"] == "cancelled"
    assert count(session_factory, PlannedEvent) == 0


def test_proposal_uses_authoritative_text_and_preserves_original_name(client, session_factory, logged_in, monkeypatch):
    original_name = "ООО Тестовый Вектор"
    seen = mock_tools(monkeypatch, [("propose_create_plan", {"body": {
        "direction": "out", "amount_minor": 12345, "due_date": "2026-11-01",
        "counterparty_name": original_name,
    }})], final_text="Я уже сохранил платёж и заменил имя на Контрагент-deadbeef.")
    response = client.post(chat_url(logged_in), json=request(logged_in))
    assert response.status_code == 200
    reply = response.json()
    assert "Я уже сохранил" not in reply["text"] and "deadbeef" not in reply["text"]
    assert "ожидают вашего подтверждения" in reply["text"]
    assert "не меняет имена" in reply["text"]
    action = reply["cards"][0]["data"]
    assert action["arguments"]["body"]["counterparty_name"] == original_name
    assert count(session_factory, PlannedEvent) == 0
    tool_copy = next(m["content"] for m in seen[-1] if m["role"] == "tool")
    assert original_name not in tool_copy and "Контрагент-" in tool_copy
    confirmed = client.post(action_url(logged_in, action["action_id"]), json={"decision": "confirm"})
    assert confirmed.status_code == 200
    with session_factory() as session:
        plan = session.scalar(select(PlannedEvent))
        assert plan.counterparty_name == original_name
        assert plan.amount_minor == 12345


def test_proposal_does_not_hide_later_provider_error(client, logged_in, monkeypatch):
    calls = 0

    def complete(self, messages, tools, timeout):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AppError(503, "assistant_provider_unavailable", "Провайдер недоступен")
        return {"role": "assistant", "tool_calls": [{"id": "proposal", "type": "function", "function": {
            "name": "propose_create_plan", "arguments": json.dumps({"body": {
                "direction": "out", "amount_minor": 12345, "due_date": "2026-11-01"}})}}]}

    monkeypatch.setattr(OpenRouterClient, "complete", complete)
    reply = client.post(chat_url(logged_in), json=request(logged_in)).json()
    assert reply["error_code"] == "assistant_provider_unavailable"
    assert "Провайдер недоступен" in reply["text"]
    assert reply["cards"][0]["data"]["status"] == "pending"


@pytest.mark.parametrize("failed_call,expected", [
    (("propose_create_plan", {"body": {"direction": "out", "amount_minor": -1}}),
     "Проверьте формат и обязательные поля"),
    (("confirm_action", {}), "Запрошенная операция недоступна"),
    (("propose_update_plan", {"event_id": "00000000-0000-0000-0000-000000000001",
                              "body": {"amount_minor": 100}}), "Объект выбранного счёта не найден"),
])
def test_partial_tool_failure_is_visible_with_prepared_action(
    client, session_factory, logged_in, monkeypatch, failed_call, expected,
):
    mock_tools(monkeypatch, [("propose_create_plan", {"body": {
        "direction": "out", "amount_minor": 12345, "due_date": "2026-11-01"}}), failed_call],
        final_text="Все действия выполнены, ошибок нет.")
    response = client.post(chat_url(logged_in), json=request(logged_in))
    assert response.status_code == 200
    reply = response.json()
    assert len(reply["cards"]) == 1 and reply["cards"][0]["data"]["status"] == "pending"
    assert "Некоторые запросы не обработаны" in reply["text"] and expected in reply["text"]
    assert "Все действия выполнены" not in reply["text"]
    assert count(session_factory, PlannedEvent) == 0


@pytest.mark.parametrize("expired", [True, False])
def test_stale_or_expired_no_write(client, session_factory, logged_in, monkeypatch, expired):
    action = propose(client, logged_in, monkeypatch)
    if expired:
        with session_factory() as s:
            s.get(AssistantAction, uuid.UUID(action)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
            s.commit()
    else:
        response = client.post(f"/api/v1/companies/{logged_in['company_id']}/planned-events", json={
            "account_id": logged_in["account_id"], "direction": "out", "amount_minor": 900,
            "due_date": "2026-11-01"})
        assert response.status_code == 201, response.text
    before = count(session_factory, PlannedEvent)
    reply = client.post(action_url(logged_in, action), json={"decision": "confirm"})
    assert reply.status_code == 409, reply.text
    assert count(session_factory, PlannedEvent) == before


def test_action_account_and_user_scope_and_csrf(client, session_factory, logged_in, monkeypatch):
    action = propose(client, logged_in, monkeypatch)
    with session_factory() as s:
        company = s.get(Company, uuid.UUID(logged_in["company_id"]))
        other = make_account(s, company, name="Другой счёт")
        user = make_user(s, "other@example.com", PASSWORD)
        s.add(CompanyMember(company_id=company.id, user_id=user.id, role="owner"))
        s.commit()
        other_id = str(other.id)
    wrong = {**logged_in, "account_id": other_id}
    assert client.post(action_url(wrong, action), json={"decision": "confirm"}).status_code == 404
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post(action_url(logged_in, action), json={"decision": "confirm"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    reply = client.post("/api/v1/auth/login", json={"email": "other@example.com", "password": PASSWORD})
    client.headers["X-CSRF-Token"] = reply.json()["csrf_token"]
    assert client.post(action_url(logged_in, action), json={"decision": "confirm"}).status_code == 404
    assert count(session_factory, PlannedEvent) == 0


def test_viewer_cannot_propose_or_confirm(client, session_factory, logged_in, monkeypatch):
    action = propose(client, logged_in, monkeypatch)
    with session_factory() as s:
        member = s.scalar(select(CompanyMember).where(CompanyMember.company_id == uuid.UUID(logged_in["company_id"])))
        member.role = "viewer"
        s.commit()
    mock_tools(monkeypatch, [("propose_create_plan", {"body": {
        "direction": "out", "amount_minor": 100, "due_date": "2026-11-01"}})])
    reply = client.post(chat_url(logged_in), json=request(logged_in))
    assert reply.status_code == 200, reply.text
    assert reply.json()["cards"] == []
    assert client.post(action_url(logged_in, action), json={"decision": "confirm"}).status_code == 403
    assert count(session_factory, PlannedEvent) == 0


def test_chat_request_idempotency(client, session_factory, logged_in, monkeypatch):
    seen = mock_tools(monkeypatch, [("list_transactions", {})])
    body = request(logged_in)
    first = client.post(chat_url(logged_in), json=body)
    assert first.status_code == 200, first.text
    assert client.post(chat_url(logged_in), json=body).json() == first.json()
    assert len(seen) == 2
    body["messages"][0]["content"] = "Другой запрос"
    assert client.post(chat_url(logged_in), json=body).status_code == 409
    assert count(session_factory, AssistantTurn) == 1


@pytest.mark.parametrize("malformed", [None, "bad", [None], [{"id": 5, "function": {}}]])
def test_malformed_response_safe(client, logged_in, monkeypatch, malformed):
    monkeypatch.setattr(OpenRouterClient, "complete", lambda *a: {"tool_calls": malformed})
    reply = client.post(chat_url(logged_in), json=request(logged_in))
    assert reply.status_code == 200, reply.text
    assert reply.json()["cards"] == []


def test_provider_failure_no_secret(client, logged_in, monkeypatch):
    def fail(*args):
        raise AppError(503, "assistant_provider_unavailable", "Провайдер недоступен")
    monkeypatch.setattr(OpenRouterClient, "complete", fail)
    reply = client.post(chat_url(logged_in), json=request(logged_in))
    assert reply.status_code == 200
    assert reply.json()["error_code"] == "assistant_provider_unavailable"


def test_upload_requires_confirmation_and_is_idempotent(client, session_factory, logged_in):
    url = f"/api/v1/companies/{logged_in['company_id']}/accounts/{logged_in['account_id']}/assistant/uploads"
    reply = client.post(url, files={"file": ("synthetic.csv", _statement_csv(date(2026, 10, 24)), "text/csv")},
                        data={"import_kind": "statement", "mapping": json.dumps(_MAPPING)})
    assert reply.status_code == 200, reply.text
    assert count(session_factory, BankTransaction) == 0
    action = reply.json()["cards"][1]["data"]["action_id"]
    assert client.post(action_url(logged_in, action), json={"decision": "confirm"}).status_code == 200
    assert count(session_factory, BankTransaction) == 28
    assert client.post(action_url(logged_in, action), json={"decision": "confirm"}).status_code == 200
    assert count(session_factory, BankTransaction) == 28


def test_foreign_account_rejected_before_provider(client, session_factory, logged_in, monkeypatch):
    with session_factory() as s:
        other = make_company(s, "Чужая компания")
        account = make_account(s, other)
        s.commit()
        account_id = str(account.id)
    seen = mock_tools(monkeypatch, [])
    body = request(logged_in)
    body["account_id"] = account_id
    assert client.post(chat_url(logged_in), json=body).status_code == 404
    assert seen == []


def test_projection_hides_raw_fields():
    encoded = ModelProjection.encode({"purpose": "секретное назначение", "counterparty_ref": "7701234567",
                                      "counterparty_name": "ООО Секрет", "amount_minor": 12300,
                                      "input_snapshot": {"transactions": ["raw"]}})
    assert "секретное" not in encoded and "7701234567" not in encoded and "ООО Секрет" not in encoded
    assert "12300" in encoded and "Контрагент-" in encoded


def test_projection_masks_pulse_embedded_names():
    source = {"clients": {"top_client": {"name": "ООО Canary"}, "message": "Позвоните ООО Canary"},
              "actions": [{"title": "Платёж ООО Canary задерживается"}], "source_ref": "Договор SECRET"}
    encoded = ModelProjection.encode(source)
    assert "Canary" not in encoded and "SECRET" not in encoded
    assert "ООО Canary" in source["clients"]["message"]  # Карточка в кабинете остаётся исходной.


def test_pulse_stress_only_name_uses_private_frozen_aliases():
    from app.modules.assistant.gateway import SiteGateway
    gateway = object.__new__(SiteGateway)
    gateway.private_values = set()
    gateway.remember_private_values({"schema_version": 1, "input": {"txns": [
        {"counterparty_name": "TOP_CLIENT", "counterparty_ref": "7701234567"},
        {"counterparty_name": "SECOND_CLIENT_CANARY", "counterparty_ref": "7707654321"}]}})
    source = {"clients": {"top_client": {"name": "TOP_CLIENT"}, "at_risk": [],
              "stress": [{"title": "Задержка SECOND_CLIENT_CANARY", "text": "Клиент SECOND_CLIENT_CANARY"}]}}
    encoded = ModelProjection.encode(source, gateway.private_values)
    assert "TOP_CLIENT" not in encoded and "SECOND_CLIENT_CANARY" not in encoded
    assert "SECOND_CLIENT_CANARY" in source["clients"]["stress"][0]["title"]


def test_private_aliases_do_not_corrupt_machine_values():
    source = {"as_of": "2026-10-24", "direction": "in",
              "source_ref": "00000000-0000-0000-0000-000000000000",
              "message": "Клиенты 2026 и in", "name": "0000"}
    clean = ModelProjection.sanitize(source, {"2026", "in", "0000"})
    assert all(clean[key] == source[key] for key in ("as_of", "direction", "source_ref"))
    assert "2026" not in clean["message"] and clean["name"].startswith("Контрагент-")


def test_forecast_tools_use_real_site_results(client, session_factory, logged_in, monkeypatch):
    ctx = logged_in
    preview = client.post(f"/api/v1/companies/{ctx['company_id']}/imports",
        files={"file": ("synthetic.csv", _statement_csv(date(2026, 10, 24)), "text/csv")},
        data={"account_id": ctx["account_id"], "mapping": json.dumps(_MAPPING)}).json()
    assert client.post(f"/api/v1/imports/{preview['import_id']}/commit").status_code == 200
    mock_tools(monkeypatch, [("propose_forecast", {"as_of": "2026-10-24", "horizon_days": 30})])
    reply = client.post(chat_url(ctx), json=request(ctx)).json()
    action = reply["cards"][0]["data"]["action_id"]
    accepted = client.post(action_url(ctx, action), json={"decision": "confirm"})
    assert accepted.status_code == 200, accepted.text
    run = accepted.json()["cards"][1]["data"]["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    mock_tools(monkeypatch, [("show_forecast", {"forecast_id": run}),
                            ("show_explanations", {"forecast_id": run}),
                            ("show_pulse", {"forecast_id": run, "buffer_minor": 12345}),
                            ("show_plan_fact", {"as_of": "2026-10-24"}),
                            ("summarize_transactions", {}), ("list_forecasts", {})])
    answer = client.post(chat_url(ctx), json=request(ctx))
    assert answer.status_code == 200, answer.text
    cards = answer.json()["cards"]
    assert len(cards) == 6, answer.text
    assert cards[0]["data"] == client.get(f"/api/v1/forecasts/{run}").json()
    assert cards[2]["data"]["cash"]["buffer_minor"] == 12345
    assert sum(item["count"] for item in cards[4]["data"]["items"]) == 28
    # Сценарий проходит тот же worker, после него сравнение читает реальный frozen-результат.
    mock_tools(monkeypatch, [("propose_scenario", {"forecast_id": run, "body": {"changes": [{
        "kind": "add_expense", "amount_minor": 10000, "on_date": "2026-10-25"}]}})])
    proposal = client.post(chat_url(ctx), json=request(ctx)).json()["cards"][0]["data"]["action_id"]
    accepted = client.post(action_url(ctx, proposal), json={"decision": "confirm"})
    assert accepted.status_code == 200, accepted.text
    scenario = accepted.json()["cards"][1]["data"]["forecast_run_id"]
    _run_worker_until_idle(session_factory)
    mock_tools(monkeypatch, [("show_comparison", {"forecast_id": scenario})])
    compared = client.post(chat_url(ctx), json=request(ctx)).json()["cards"][0]
    assert compared["kind"] == "comparison"
    assert compared["data"] == client.get(f"/api/v1/forecasts/{scenario}/comparison").json()


def test_daily_quota_and_unauthorized_tool(client, session_factory, logged_in, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "assistant_daily_turns", 1)
    mock_tools(monkeypatch, [("confirm_action", {"decision": "confirm"})])
    assert client.post(chat_url(logged_in), json=request(logged_in)).status_code == 200
    assert client.post(chat_url(logged_in), json=request(logged_in)).status_code == 429
    assert count(session_factory, PlannedEvent) == 0


def test_tool_repetition_does_not_duplicate_proposals(client, session_factory, logged_in, monkeypatch):
    seen_tools = []

    def complete(self, messages, tools, timeout):
        seen_tools.append(tools)
        if not tools:
            return {"role": "assistant", "content": "Готово только предложение, проверьте карточку."}
        return {"role": "assistant", "tool_calls": [{"id": f"call{len(seen_tools)}", "type": "function",
            "function": {"name": "propose_create_plan", "arguments": json.dumps({"body": {
                "direction": "out", "amount_minor": 100, "due_date": "2026-11-01"}})}}]}

    monkeypatch.setattr(OpenRouterClient, "complete", complete)
    response = client.post(chat_url(logged_in), json=request(logged_in))
    assert response.status_code == 200, response.text
    assert len(response.json()["cards"]) == 1
    assert seen_tools[-1] == []
    assert count(session_factory, AssistantAction) == 1
    assert count(session_factory, PlannedEvent) == 0


def test_invalid_forecast_date_rejected_before_proposal(client, session_factory, logged_in, monkeypatch):
    mock_tools(monkeypatch, [("propose_forecast", {"as_of": "0001-01-01"})])
    response = client.post(chat_url(logged_in), json=request(logged_in))
    assert response.status_code == 200, response.text
    assert response.json()["cards"] == []
    assert count(session_factory, AssistantAction) == 0

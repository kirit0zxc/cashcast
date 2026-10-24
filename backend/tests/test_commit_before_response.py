"""ASGI-проверка момента ответа: TestClient сам ждёт cleanup и скрывает эту гонку."""

import asyncio

from sqlalchemy import event


def test_database_commit_happens_before_response_start(client, monkeypatch):
    observed = []
    app = client.app
    factory = app.state.session_factory

    def tracked_factory():
        session = factory()
        event.listen(session, "after_commit", lambda _: observed.append("commit"))
        return session

    monkeypatch.setattr(app.state, "session_factory", tracked_factory)

    async def invoke():
        response_done = asyncio.Event()
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await response_done.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                observed.append("response")
                assert message["status"] == 200
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_done.set()

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "scheme": "http", "method": "GET", "path": "/api/v1/health",
                   "raw_path": b"/api/v1/health", "query_string": b"", "headers": [],
                   "server": ("test", 80), "client": ("test", 123)}, receive, send)

    asyncio.run(invoke())
    assert observed == ["commit", "response"]


def test_commit_error_returns_failure_instead_of_already_sent_success(client, monkeypatch):
    factory = client.app.state.session_factory
    rolled_back = []
    error_detail = "private-financial-error"

    def failing_factory():
        session = factory()

        def fail_commit():
            raise RuntimeError(error_detail)

        monkeypatch.setattr(session, "commit", fail_commit)
        event.listen(session, "after_rollback", lambda _: rolled_back.append(True))
        return session

    monkeypatch.setattr(client.app.state, "session_factory", failing_factory)
    response = client.get("/api/v1/health")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert error_detail not in response.text
    assert rolled_back

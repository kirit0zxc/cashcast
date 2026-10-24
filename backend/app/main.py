"""Сборка FastAPI-приложения: lifespan, middleware, обработчики ошибок, роутеры v1."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import (
    accounts,
    auth,
    comparisons,
    forecast_history,
    forecasts,
    health,
    imports,
    obligations,
    plan_fact,
    planned_events,
    transactions,
)
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.request_context import RequestContextMiddleware

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CashCast API",
        version="0.1.0",
        description="Сервис прогноза денежного потока для малого бизнеса (рабочее название CashCast).",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    for module in (health, auth, accounts, imports, obligations, transactions, planned_events,
                   plan_fact, forecasts, forecast_history, comparisons):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()

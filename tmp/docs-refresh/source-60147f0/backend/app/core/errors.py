"""Единый формат ошибки API: {"error": {"code", "message", "field_errors", "request_id"}}.

Фронтенд опирается только на `code` (стабильный машинный идентификатор);
`message` — человекочитаемый текст на русском, может меняться.
"""

import logging
import traceback
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Ожидаемая ошибка предметной области. Всё остальное превращается в 500 internal_error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or []


def not_found(what: str = "Объект") -> AppError:
    # Для чужих компаний тоже 404, а не 403: не раскрываем факт существования объекта.
    return AppError(404, "not_found", f"{what} не найден")


def not_implemented(owner: str) -> AppError:
    return AppError(
        501,
        "not_implemented",
        f"Ручка описана в контракте v1, реализация ещё не готова (владелец: {owner})",
    )


def error_body(code: str, message: str, field_errors: list[dict[str, str]] | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "field_errors": field_errors or [],
            "request_id": get_request_id(),
        }
    }


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def _loc_to_field(loc: tuple[Any, ...]) -> str:
    # ("body", "items", 0, "amount") -> "items.0.amount"; источник (body/query/path) отбрасываем.
    parts = [str(p) for p in loc[1:]] if loc and loc[0] in {"body", "query", "path"} else loc
    return ".".join(str(p) for p in parts) or "request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.field_errors),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Значения полей в ответ не копируем: там может быть назначение платежа или пароль.
        field_errors = [
            {"field": _loc_to_field(tuple(e.get("loc", ()))), "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Некорректные данные запроса", field_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
        if exc.status_code == 404:
            message = "Ресурс не найден"
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message))



def internal_error_response(exc: Exception) -> JSONResponse:
    # Пишем тип исключения и стек кода, но не str(exc): текст может содержать данные клиента.
    logger.error(
        "unhandled error type=%s request_id=%s\n%s",
        type(exc).__name__,
        get_request_id(),
        "".join(traceback.format_tb(exc.__traceback__)),
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "Внутренняя ошибка сервера"),
    )

"""request_id для связи ответа API, логов и сообщения пользователя об ошибке."""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

access_logger = logging.getLogger("app.access")


def get_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Принимаем id от nginx/клиента только безопасного вида, иначе генерируем свой.
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Ловим здесь, а не в exception_handler(Exception): тот срабатывает снаружи
            # middleware, когда request_id уже сброшен и не попал бы в ответ.
            from app.core.errors import internal_error_response

            response = internal_error_response(exc)
        finally:
            _request_id.reset(token)
        response.headers["X-Request-ID"] = request_id
        # Только метод, путь и статус: тело, query с фильтрами и cookie в лог не попадают.
        access_logger.info(
            "%s %s %s %.1fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request_id,
        )
        return response

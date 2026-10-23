"""Общие Pydantic-схемы ответов: ошибка и пагинация. Из них FastAPI генерирует OpenAPI."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str
    message: str


class ErrorDetail(BaseModel):
    code: str = Field(description="Машинный код ошибки; стабилен, на него опирается фронтенд")
    message: str = Field(description="Человекочитаемое описание на русском")
    field_errors: list[FieldError] = Field(default_factory=list)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(default=None, description="Курсор следующей страницы или null")


# Единый набор примеров ответов-ошибок для документации ручек.
ERROR_RESPONSES: dict = {
    401: {"model": ErrorResponse, "description": "Не аутентифицирован"},
    403: {"model": ErrorResponse, "description": "Нет доступа или CSRF"},
    404: {"model": ErrorResponse, "description": "Не найдено"},
    422: {"model": ErrorResponse, "description": "Ошибка валидации"},
    501: {"model": ErrorResponse, "description": "Ещё не реализовано"},
}

"""Чат принимает только текст пользователя/ассистента; tool/system сообщения задаёт сервер."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    account_id: uuid.UUID
    as_of: date
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)


class ChatCard(BaseModel):
    kind: Literal["forecast", "comparison", "pulse", "table", "action", "job", "import"]
    title: str
    data: dict


class ChatResponse(BaseModel):
    text: str
    cards: list[ChatCard] = Field(default_factory=list)
    error_code: str | None = None


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirm", "cancel"]

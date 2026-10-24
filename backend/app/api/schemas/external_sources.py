"""Аддитивный контракт демонстрационных интеграций."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.obligations import ObligationPreviewOut


class SourcePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    as_of: date | None = Field(None, ge=date(2, 1, 2))


class SourceDocumentOut(BaseModel):
    source_ref: str
    label: str
    document_kind: str
    direction: Literal["in", "out"]
    amount_minor: int
    due_date: date
    available_at: date
    category: str | None
    provenance: str


class ExternalPreviewOut(ObligationPreviewOut):
    provider_id: Literal["bank", "onec", "tax"]
    mode: Literal["demo"] = "demo"
    skipped_settled: int
    documents: list[SourceDocumentOut]
    preview_truncated: bool


class ExternalSourceOut(BaseModel):
    id: Literal["bank", "onec", "tax"]
    label: str
    mode: Literal["demo"] = "demo"
    description: str


class ExternalSourcesOut(BaseModel):
    items: list[ExternalSourceOut]
    warning: str

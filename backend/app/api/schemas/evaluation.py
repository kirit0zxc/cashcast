"""Контракт проверки уже импортированного контрольного набора."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    account_id: UUID
    as_of: date
    horizon_days: int = Field(default=30, ge=1, le=90)
    folds: int = Field(default=1, ge=1, le=12)
    threshold: float = Field(default=0.5, ge=0, le=1)
    seed: int = Field(default=42, ge=-(2**63), lt=2**63)
    complete_statement: bool = False
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class EvaluationOut(BaseModel):
    id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    error_code: str | None = None
    report: dict[str, JsonValue] | None = None

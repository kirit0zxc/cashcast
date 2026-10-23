"""HTTP-контракт csv-obligations-v1: preview без исходных значений ошибочных строк."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class ObligationRowErrorOut(BaseModel):
    row: int
    field: str
    code: str


class ObligationPreviewOut(BaseModel):
    import_id: str
    status: Literal["previewed", "committed"]
    source_name: str
    as_of: date
    total_rows: int
    valid_count: int
    error_count: int
    sample_errors: list[ObligationRowErrorOut]
    reused: bool


class ObligationCommitOut(BaseModel):
    import_id: str
    status: Literal["committed"]
    inserted: int
    skipped_existing: int

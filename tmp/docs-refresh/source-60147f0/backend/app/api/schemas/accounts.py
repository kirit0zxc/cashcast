"""Аддитивный HTTP-контракт app-api-v1, согласован A-001/B-002."""

from pydantic import BaseModel

from app.api.schemas.models import ColumnMappingIn


class AccountOut(BaseModel):
    id: str
    company_id: str
    name: str
    currency: str


class AccountList(BaseModel):
    items: list[AccountOut]


class ImportPreset(BaseModel):
    id: str
    name: str
    mapping: ColumnMappingIn


class ImportPresetList(BaseModel):
    items: list[ImportPreset]

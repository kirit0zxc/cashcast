"""Проверка живости сервиса и доступности БД."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_db, scope="function")) -> dict:
    # Лёгкий ping БД: контейнер считается здоровым, только если соединение живо.
    session.execute(text("SELECT 1"))
    return {"status": "ok"}

"""Аутентификация по серверной сессии и изоляция по компании.

Cookie HttpOnly + SameSite=Lax; на изменяющих запросах — double-submit CSRF.
Все доступы к данным компании проходят через require_company_access: пользователь A
не видит компанию B (проверка по таблице company_member).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import CompanyMember, User, UserSession
from app.core.security import token_hash


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    email: str
    session_id: str
    csrf_token: str


def get_current_user(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AppError(401, "unauthorized", "Требуется вход")
    us = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    if us is None or us.expires_at <= datetime.now(UTC):
        raise AppError(401, "unauthorized", "Сессия недействительна или истекла")
    user = session.get(User, us.user_id)
    if user is None:
        raise AppError(401, "unauthorized", "Пользователь не найден")

    # Небезопасные методы требуют совпадения CSRF-токена из заголовка с токеном сессии.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        header = request.headers.get(settings.csrf_header_name, "")
        if not header or header != us.csrf_token:
            raise AppError(403, "csrf_failed", "Неверный или отсутствующий CSRF-токен")

    return CurrentUser(
        id=str(user.id), email=user.email, session_id=str(us.id), csrf_token=us.csrf_token
    )


def require_company_access(
    company_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> str:
    member = session.get(CompanyMember, {"company_id": company_id, "user_id": uuid.UUID(user.id)})
    if member is None:
        # 404, а не 403: не подтверждаем даже существование чужой компании.
        raise AppError(404, "not_found", "Компания не найдена")
    return str(company_id)

"""Вход, выход и информация о текущем пользователе."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas.common import ERROR_RESPONSES
from app.api.schemas.models import CompanyBrief, LoginRequest, MeResponse
from app.core.auth import CurrentUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.deps import get_db
from app.core.errors import AppError
from app.core.models import Company, CompanyMember, User, UserSession
from app.core.security import new_token, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


def _set_session_cookies(response: Response, settings: Settings, token: str, csrf: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    # CSRF-cookie читается JS намеренно (double-submit): не HttpOnly.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/login", response_model=MeResponse)
def login(
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    user = session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    # Одинаковая ошибка при неверном email и пароле: не раскрываем, какой из них неверен.
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(401, "invalid_credentials", "Неверный email или пароль")

    token = new_token()
    csrf = new_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(token),
            csrf_token=csrf,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours),
        )
    )
    session.flush()
    _set_session_cookies(response, settings, token, csrf)
    return _me(session, user.id, user.email, csrf)


@router.get("/me", response_model=MeResponse)
def me(
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
) -> MeResponse:
    import uuid

    return _me(session, uuid.UUID(user.id), user.email, user.csrf_token)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings),
) -> Response:
    # Выход — удаление серверной сессии, а не только cookie.
    import uuid

    session.query(UserSession).filter(UserSession.id == uuid.UUID(user.session_id)).delete()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    response.status_code = 204
    return response


def _me(session: Session, user_id, email: str, csrf: str) -> MeResponse:
    rows = session.execute(
        select(Company.id, Company.name, CompanyMember.role)
        .join(CompanyMember, CompanyMember.company_id == Company.id)
        .where(CompanyMember.user_id == user_id)
        .order_by(Company.name)
    ).all()
    return MeResponse(
        id=str(user_id),
        email=email,
        csrf_token=csrf,
        companies=[CompanyBrief(id=str(r[0]), name=r[1], role=r[2]) for r in rows],
    )

"""Сид демо-данных: пользователь, две компании (для проверки изоляции) и счёт.

Запуск: `python -m app.scripts.seed`. Идемпотентен — повторный запуск не плодит дубли.
Пароль демо-пользователя берётся из настроек (CC_DEMO_PASSWORD); в репозитории его нет.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.models import Account, Company, CompanyMember, User
from app.core.security import hash_password


def seed() -> None:
    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as session:
        email = settings.demo_email.lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name="Демо-предприниматель",
                password_hash=hash_password(settings.demo_password),
            )
            session.add(user)
            session.flush()

        # Компания A — пользователя; компания B — чужая, для теста изоляции доступа.
        company = _ensure_company(session, "ООО «Ромашка» (демо)")
        _ensure_company(session, "ООО «Чужая компания» (демо, без доступа)")
        if (
            session.get(CompanyMember, {"company_id": company.id, "user_id": user.id})
            is None
        ):
            session.add(CompanyMember(company_id=company.id, user_id=user.id, role="owner"))

        if session.scalar(select(Account).where(Account.company_id == company.id)) is None:
            session.add(Account(company_id=company.id, name="Расчётный счёт", currency="RUB"))

        session.commit()
        print(f"seed ok: user={email} company={company.id}")


def _ensure_company(session, name: str) -> Company:
    company = session.scalar(select(Company).where(Company.name == name))
    if company is None:
        company = Company(name=name)
        session.add(company)
        session.flush()
    return company


if __name__ == "__main__":  # pragma: no cover
    seed()

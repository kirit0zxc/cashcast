"""Хелперы для тестов: создать пользователя, компанию, доступ и счёт прямо в БД."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.models import Account, Company, CompanyMember, User
from app.core.security import hash_password


def make_user(session: Session, email: str, password: str) -> User:
    user = User(email=email.lower(), display_name=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def make_company(session: Session, name: str, owner: User | None = None) -> Company:
    company = Company(name=name)
    session.add(company)
    session.flush()
    if owner is not None:
        session.add(CompanyMember(company_id=company.id, user_id=owner.id, role="owner"))
        session.flush()
    return company


def make_account(session: Session, company: Company, name: str = "Счёт") -> Account:
    acc = Account(company_id=company.id, name=name, currency="RUB")
    session.add(acc)
    session.flush()
    return acc

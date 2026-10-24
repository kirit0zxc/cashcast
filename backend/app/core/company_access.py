"""Единая граница членства и права записи, включая ручки с UUID объекта вместо компании."""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import CompanyMember


class CompanyAccess:
    def __init__(self, session: Session):
        self.session = session

    def require(self, user_id: str, company_id: str | uuid.UUID, *, write: bool = False) -> None:
        member = self.session.get(CompanyMember, {
            "company_id": uuid.UUID(str(company_id)), "user_id": uuid.UUID(str(user_id)),
        })
        if member is None:
            # Чужое существование не раскрывается независимо от метода запроса.
            raise AppError(404, "not_found", "Компания не найдена")
        if write and member.role != "owner":
            raise AppError(403, "read_only_company", "Роль viewer разрешает только просмотр компании")

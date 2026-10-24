"""Неизменяемое содержимое банковской операции отдельно от остатка и категории."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.models import BankTransaction
    from app.modules.imports.parser import ParsedRow


class BankOperationIdentity:
    """Одинаковый внешний ID разрешает пропуск только одинакового источника."""

    @staticmethod
    def payload(row: BankTransaction | ParsedRow) -> tuple:
        # Категорию исправляет пользователь; остаток относится к дню выписки.
        # Позиция строки, import ID и имя файла также не меняют финансовый факт.
        return (
            row.booked_on, row.amount_minor, str(row.direction), row.currency,
            row.counterparty_ref or None, row.counterparty_name or None, row.purpose or None,
        )

    @classmethod
    def matches(cls, first: BankTransaction | ParsedRow, second: BankTransaction | ParsedRow) -> bool:
        return first.external_id == second.external_id and cls.payload(first) == cls.payload(second)

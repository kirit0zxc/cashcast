"""Категоризация операций — заглушка. Владелец: Дима (modules/categorization/).

Текущая реализация ничего не угадывает: всё → OTHER с confidence 0 и честной причиной.
Так сквозной путь работает (категория всегда проставлена), но фальшивых меток нет.
Дима заменит на правила по назначению платежа и словарь контрагентов.
"""

from __future__ import annotations

from app.modules.contracts import Categorizer, Category, CategoryAssignment, TxnDTO


class StubCategorizer:
    """Реализует протокол Categorizer. Заменить на правила категоризации."""

    def categorize(self, txns: list[TxnDTO]) -> list[CategoryAssignment]:
        # TODO(Дима): правила по purpose/counterparty_ref, словарь категорий, обучаемость.
        return [
            CategoryAssignment(
                transaction_id=t.id,
                category=Category.OTHER,
                reason="Заглушка категоризации: правила ещё не реализованы.",
                confidence=0.0,
            )
            for t in txns
        ]


def get_categorizer() -> Categorizer:
    return StubCategorizer()

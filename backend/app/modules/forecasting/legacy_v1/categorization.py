"""Объяснимые правила. Confidence — сила правила, не калиброванная вероятность."""

from __future__ import annotations

import re

from app.modules.contracts import Categorizer, Category, CategoryAssignment, Direction, TxnDTO

_LOAN_PATTERN = r"\b(?:погашени\w*|возврат|выдач\w*|получени\w*) (?:кредит\w*|займ\w*)|\bлизингов\w* платеж"
_RULES = (
    (
        Category.TRANSFER,
        r"собственн\w* средств|между сво\w* счет|перевод со сво|пополнени\w* (?:счета )?владельц",
        None,
    ),
    (Category.PAYROLL, r"зарплат|заработн\w* плат|аванс (?:по |в счет )?зар|оплат\w* труда", Direction.OUT),
    (Category.TAX, r"\bенп\b|един\w* налогов\w* плат|уплат\w* налог|налогов\w* платеж|страхов\w* взнос", Direction.OUT),
    (Category.FEES, r"комисси\w*|расчетно[- ]кассов\w* обслуж|обслуживани\w* счета|банковск\w* сбор", Direction.OUT),
    (
        Category.LOAN,
        _LOAN_PATTERN,
        None,
    ),
    (Category.RENT, r"аренд\w*", Direction.OUT),
    (
        Category.SALES,
        r"выручк\w*|эквайринг\w*|оплат\w* (?:за |по счету за )(?:товар|услуг|работ)|реализаци\w*",
        Direction.IN,
    ),
    (
        Category.PURCHASES,
        r"закуп\w*|поставк\w*|оплат\w* (?:за |по счету за )(?:товар|материал|сырье|услуг|работ)",
        Direction.OUT,
    ),
)


def normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().replace("ё", "е").split())


class RuleCategorizer:
    def categorize(self, txns: list[TxnDTO]) -> list[CategoryAssignment]:
        result = []
        for txn in txns:
            if txn.category in {category.value for category in Category}:
                result.append(
                    CategoryAssignment(txn.id, Category(txn.category), "Сохранённая категория операции.", 1.0)
                )
                continue
            purpose = normalize(txn.purpose)
            # Возврат нельзя считать выручкой без связи с исходной операцией.
            if "возврат" in purpose and not re.search(_LOAN_PATTERN, purpose):
                result.append(
                    CategoryAssignment(txn.id, Category.OTHER, "Возврат требует проверки исходной операции.", 0.0)
                )
                continue
            for category, pattern, direction in _RULES:
                if (direction is None or txn.direction == direction) and re.search(pattern, purpose):
                    result.append(CategoryAssignment(txn.id, category, f"Правило назначения: {category.value}.", 0.85))
                    break
            else:
                result.append(CategoryAssignment(txn.id, Category.OTHER, "Нет однозначного правила назначения.", 0.0))
        return result


def get_categorizer() -> Categorizer:
    return RuleCategorizer()

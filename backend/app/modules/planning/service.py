"""Регулярности и сопоставление план/факт — заглушки. Владелец: Дима (modules/planning/).

Заглушки возвращают пустой результат (ничего не найдено / нечего сопоставлять), а не
выдуманные группы: лучше «не найдено», чем ложная регулярность. Дима заменит обе.
"""

from __future__ import annotations

from datetime import date

from app.modules.contracts import (
    MatchProposal,
    PlannedEventDTO,
    PlannedEventMatcher,
    RecurrenceDetector,
    RecurrenceGroup,
    TxnDTO,
)


class StubRecurrenceDetector:
    def detect(self, txns: list[TxnDTO], as_of: date) -> list[RecurrenceGroup]:
        # TODO(Дима): поиск по контрагенту/категории/направлению и недельным/месячным интервалам,
        # минимум несколько повторов, confidence и next_expected_date. Без утечки будущего за as_of.
        return []


class StubPlannedEventMatcher:
    def match(self, planned: list[PlannedEventDTO], txns: list[TxnDTO]) -> list[MatchProposal]:
        # TODO(Дима): сопоставление без двойного счёта; однозначное — auto_confirm, иначе кандидат.
        return []


def get_recurrence_detector() -> RecurrenceDetector:
    return StubRecurrenceDetector()


def get_planned_event_matcher() -> PlannedEventMatcher:
    return StubPlannedEventMatcher()

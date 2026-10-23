"""Фабрики чистых сервисов планирования."""

from __future__ import annotations

from app.modules.contracts import PlannedEventMatcher, RecurrenceDetector
from app.modules.planning.matching import ConservativePlannedEventMatcher
from app.modules.planning.recurrence import CalendarRecurrenceDetector


def get_recurrence_detector() -> RecurrenceDetector:
    return CalendarRecurrenceDetector()


def get_planned_event_matcher() -> PlannedEventMatcher:
    return ConservativePlannedEventMatcher()

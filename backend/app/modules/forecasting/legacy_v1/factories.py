"""Фабрика замороженной регулярности для воспроизводимости модели1.0."""

from app.modules.forecasting.legacy_v1.recurrence import CalendarRecurrenceDetector


def get_recurrence_detector():
    return CalendarRecurrenceDetector()

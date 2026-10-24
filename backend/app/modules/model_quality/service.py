"""Чтение упакованного отчёта: ни обучения, ни банковских строк на HTTP-запросе."""

from pathlib import Path

from pydantic import ValidationError

from app.api.schemas.model_quality import ModelQualityOut
from app.core.errors import AppError

REPORT_PATH = Path(__file__).with_name("report.json")


class ModelQualityService:
    @staticmethod
    def read() -> ModelQualityOut:
        try:
            return ModelQualityOut.model_validate_json(REPORT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            # Повреждённые/отсутствующие измерения нельзя подменять нулями или успехом.
            raise AppError(503, "quality_report_unavailable", "Отчёт качества временно недоступен") from None

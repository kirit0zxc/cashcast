"""Все вошедшие пользователи могут читать общие обезличенные метрики модели."""

from fastapi import APIRouter, Depends, Response

from app.api.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.api.schemas.model_quality import ModelQualityOut
from app.core.auth import CurrentUser, get_current_user
from app.modules.model_quality.service import ModelQualityService

router = APIRouter(tags=["model-quality"], responses=ERROR_RESPONSES)


@router.get("/models/quality", response_model=ModelQualityOut,
            responses={503: {"model": ErrorResponse, "description": "Отчёт качества временно недоступен"}})
def get_model_quality(response: Response, user: CurrentUser = Depends(get_current_user)) -> ModelQualityOut:
    response.headers["Cache-Control"] = "private, no-store"
    return ModelQualityService.read()

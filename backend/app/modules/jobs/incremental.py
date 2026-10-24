"""Выбор checkpoint внутри того же счёта/компании; отсутствие — обычный полный расчёт."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ForecastRun
from app.modules.contracts import ForecastInput
from app.modules.forecasting.v2.incremental_state import STATE_KEY, IncrementalState


class ForecastCheckpointRepository:
    def __init__(self, session: Session):
        self.session = session

    def find(self, run: ForecastRun, data: ForecastInput) -> tuple[dict | None, str | None]:
        if run.scenario_hash or data.scenario:
            return None, None
        # Ограниченный поиск: при большом числе старых версий безопаснее пересчитать.
        candidates = self.session.scalars(select(ForecastRun).where(
            ForecastRun.id != run.id, ForecastRun.company_id == run.company_id,
            ForecastRun.account_id == run.account_id, ForecastRun.model_version == run.model_version,
            ForecastRun.as_of == run.as_of, ForecastRun.horizon_days == run.horizon_days,
            ForecastRun.seed == run.seed, ForecastRun.scenario_hash == "",
            ForecastRun.status == "succeeded",
        ).order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc()).limit(8)).all()
        for candidate in candidates:
            state = (candidate.details or {}).get(STATE_KEY)
            if IncrementalState.unpack(data, state) is not None:
                return state, str(candidate.id)
        return None, None

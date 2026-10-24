"""Явный повтор исчерпанного временного forecast-сбоя без нового input или сброса fencing."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.models import ForecastRun, Job


class ForecastRetryRecovery:
    # Только известные коды инфраструктурного сбоя. Не классифицируем произвольный
    # RuntimeError/ValueError как временный и не повторяем permanent input/model errors.
    TRANSIENT_ERRORS = frozenset({
        "ConnectionError", "TimeoutError", "OperationalError", "InterfaceError",
        "DisconnectionError", "lease_expired_attempts_exhausted",
    })
    RETRY_ATTEMPTS = 3

    def __init__(self, session: Session):
        self.session = session

    def resume(self, run: ForecastRun, job: Job) -> bool:
        if job.status != "failed":
            # Живой handler держит Job lock до конца расчёта. Обычный повтор POST
            # должен сразу вернуть pending/running, а не ждать завершения handler.
            return False
        # Как у worker: Job → ForecastRun. Account lock уже взят вызывающим POST.
        self.session.refresh(job, with_for_update=True)
        if (job.kind != "forecast" or job.status != "failed"
                or job.attempts < job.max_attempts or job.last_error not in self.TRANSIENT_ERRORS
                or str(job.company_id) != str(run.company_id)
                or (job.payload or {}).get("forecast_run_id") != str(run.id)):
            return False
        self.session.refresh(run, with_for_update=True)
        if run.status != "failed" or not run.input_snapshot:
            return False

        now = datetime.now(UTC)
        job.status = "pending"
        # Номер попытки монотонен: reset до0 создал бы ABA для старого worker/attempt.
        job.max_attempts = job.attempts + self.RETRY_ATTEMPTS
        job.run_after = now
        job.finished_at = job.lease_until = job.locked_by = job.last_error = None
        run.status = "pending"
        run.error_code = run.finished_at = None
        self.session.flush()
        return True

"""Цикл worker: тот же образ, что api, но другая команда (python -m app.worker).

Один проход run_once() берёт одно задание, выполняет обработчик в своей транзакции и
фиксирует статус. При падении обработчика — rollback и mark_failed (с повтором по lease).
"""

from __future__ import annotations

import logging
import signal
import socket
import time
from collections.abc import Callable

from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.models import Job
from app.modules.forecasting.service import UnsupportedModelVersionError
from app.modules.forecasting.v2.quality import ForecastInputError
from app.modules.jobs import queue
from app.modules.jobs.handlers import HANDLERS, mark_forecast_failed

logger = logging.getLogger("app.worker")


def run_once(factory: sessionmaker, *, worker_id: str, lease_seconds: int) -> bool:
    """Обработать одно задание. True — задание было, False — очередь пуста."""
    with factory() as session:
        expired = queue.reap_exhausted(session)
        for abandoned in expired:
            if abandoned.kind == "forecast":
                mark_forecast_failed(session, abandoned.payload, abandoned.last_error)
        job = queue.claim_next(session, worker_id=worker_id, lease_seconds=lease_seconds)
        if job is None:
            session.commit()
            return bool(expired)
        job_id, kind, payload, attempt = job.id, job.kind, dict(job.payload), job.attempts
        session.commit()

    handler: Callable | None = HANDLERS.get(kind)
    with factory() as session:
        # Пока handler жив, SKIP LOCKED не отдаёт его строку второму worker даже
        # после истечения lease. При смерти процесса БД освобождает эту блокировку.
        job = session.get(Job, job_id, with_for_update=True)
        if job is None or job.status != "running" or job.locked_by != worker_id or job.attempts != attempt:
            return True
        try:
            if handler is None:
                raise RuntimeError(f"unknown_job_kind:{kind}")
            result = handler(session, payload)
            queue.mark_succeeded(session, job, result)
            session.commit()
            logger.info("job done id=%s kind=%s", job_id, kind)
        except Exception as exc:
            session.rollback()
            # Закреплённая неизвестная модель и некорректный frozen input не
            # исправляются повтором. Политика других обработчиков остаётся прежней.
            permanent = kind == "forecast" and isinstance(exc, (ForecastInputError, UnsupportedModelVersionError))
            # Только известные аналитические исключения содержат безопасный машинный code.
            error_code = (
                exc.code if isinstance(exc, (ForecastInputError, UnsupportedModelVersionError))
                else type(exc).__name__
            )
            # В лог — только код ошибки и тип, без текста (возможны данные клиента).
            with factory() as s2:
                j2 = s2.get(Job, job_id, with_for_update=True)
                # После rollback право мог забрать другой worker: старый не пишет его статус.
                if j2 is None or j2.status != "running" or j2.locked_by != worker_id or j2.attempts != attempt:
                    return True
                queue.mark_failed(s2, j2, error_code=error_code, retryable=not permanent)
                if j2.status == "failed" and j2.kind == "forecast":
                    mark_forecast_failed(s2, j2.payload, j2.last_error)
                s2.commit()
            logger.error("job failed id=%s kind=%s type=%s", job_id, kind, type(exc).__name__)
    return True


def run_forever(factory: sessionmaker) -> None:  # pragma: no cover — запускается в контейнере
    settings = get_settings()
    worker_id = f"{socket.gethostname()}:{int(time.time())}"
    stop = {"flag": False}

    def _handle(_sig, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    logger.info("worker started id=%s", worker_id)
    while not stop["flag"]:
        try:
            had_work = run_once(
                factory, worker_id=worker_id, lease_seconds=settings.job_lease_seconds
            )
        except Exception as exc:
            # Текст исключения драйвера может содержать параметры финансового запроса.
            logger.error("worker loop error type=%s", type(exc).__name__)
            had_work = False
        if not had_work:
            time.sleep(settings.worker_poll_seconds)
    logger.info("worker stopped id=%s", worker_id)

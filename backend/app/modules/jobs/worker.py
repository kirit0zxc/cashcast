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
from app.modules.jobs import queue
from app.modules.jobs.handlers import HANDLERS

logger = logging.getLogger("app.worker")


def run_once(factory: sessionmaker, *, worker_id: str, lease_seconds: int) -> bool:
    """Обработать одно задание. True — задание было, False — очередь пуста."""
    with factory() as session:
        job = queue.claim_next(session, worker_id=worker_id, lease_seconds=lease_seconds)
        if job is None:
            session.commit()
            return False
        job_id, kind, payload = job.id, job.kind, dict(job.payload)
        session.commit()

    handler: Callable | None = HANDLERS.get(kind)
    with factory() as session:
        job = session.get(Job, job_id)
        try:
            if handler is None:
                raise RuntimeError(f"unknown_job_kind:{kind}")
            result = handler(session, payload)
            queue.mark_succeeded(session, job, result)
            session.commit()
            logger.info("job done id=%s kind=%s", job_id, kind)
        except Exception as exc:
            session.rollback()
            # В лог — только код ошибки и тип, без текста (возможны данные клиента).
            with factory() as s2:
                j2 = s2.get(Job, job_id)
                queue.mark_failed(s2, j2, error_code=type(exc).__name__)
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
        except Exception:
            logger.exception("worker loop error")
            had_work = False
        if not had_work:
            time.sleep(settings.worker_poll_seconds)
    logger.info("worker stopped id=%s", worker_id)

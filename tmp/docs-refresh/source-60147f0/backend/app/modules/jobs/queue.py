"""Очередь заданий в PostgreSQL. Без брокеров: SELECT ... FOR UPDATE SKIP LOCKED + lease.

Гарантии:
  - несколько worker не возьмут одно задание (SKIP LOCKED);
  - если worker умер, задание освободится по истечении lease и будет повторено;
  - dedupe_key не даёт поставить один и тот же расчёт дважды.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.models import Job


def enqueue(
    session: Session,
    *,
    kind: str,
    payload: dict,
    company_id: str | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    if dedupe_key:
        # Повторная постановка того же ключа возвращает существующее задание.
        stmt = (
            pg_insert(Job)
            .values(
                kind=kind,
                payload=payload,
                company_id=company_id,
                dedupe_key=dedupe_key,
                max_attempts=max_attempts,
            )
            .on_conflict_do_nothing(index_elements=[Job.dedupe_key])
            .returning(Job.id)
        )
        new_id = session.execute(stmt).scalar()
        if new_id is None:
            return session.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        return session.get(Job, new_id)

    job = Job(kind=kind, payload=payload, company_id=company_id, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, *, worker_id: str, lease_seconds: int) -> Job | None:
    """Атомарно забрать одно готовое задание и продлить аренду. None — очередь пуста."""
    now = datetime.now(UTC)
    # Готово = pending, либо running с истёкшим lease (брошено умершим worker).
    row = session.execute(
        text(
            """
            SELECT id FROM job
            WHERE run_after <= :now
              AND attempts < max_attempts
              AND (status = 'pending'
                   OR (status = 'running' AND (lease_until IS NULL OR lease_until < :now)))
            ORDER BY run_after
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"now": now},
    ).first()
    if row is None:
        return None

    job = session.get(Job, row[0])
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.lease_until = now + timedelta(seconds=lease_seconds)
    job.started_at = job.started_at or now
    session.flush()
    return job


def reap_exhausted(session: Session) -> list[Job]:
    """Закрыть брошенные последние попытки; живой handler защищён блокировкой строки."""
    now = datetime.now(UTC)
    jobs = list(session.scalars(select(Job).where(
        Job.status == "running", Job.attempts >= Job.max_attempts,
        (Job.lease_until.is_(None) | (Job.lease_until < now)),
    ).order_by(Job.id).limit(100).with_for_update(skip_locked=True)))
    for job in jobs:
        job.status = "failed"
        job.last_error = "lease_expired_attempts_exhausted"
        job.finished_at = now
        job.lease_until = None
    session.flush()
    return jobs


def mark_succeeded(session: Session, job: Job, result: dict | None = None) -> None:
    job.status = "succeeded"
    job.result = result
    job.lease_until = None
    job.finished_at = datetime.now(UTC)
    session.flush()


def mark_failed(session: Session, job: Job, *, error_code: str, retry_in_seconds: int = 30,
                retryable: bool = True) -> None:
    now = datetime.now(UTC)
    # last_error — только код/тип, без текста исключения (там могут быть данные клиента).
    job.last_error = error_code
    if not retryable or job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = now
    else:
        job.status = "pending"
        job.run_after = now + timedelta(seconds=retry_in_seconds)
    job.lease_until = None
    session.flush()

"""Тесты очереди заданий — инфраструктура интегратора: dedupe, повтор, восстановление lease.

Проверяем ровно те гарантии из плана, что заявлены в «готово, когда»:
  - повторная постановка одного расчёта не плодит задания (dedupe_key);
  - упавшее задание повторяется и уходит в failed после исчерпания попыток;
  - задание «умершего» worker (истёкший lease) забирает другой worker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.models import Job
from app.modules.jobs import queue


def test_dedupe_key_returns_same_job(session_factory) -> None:
    with session_factory() as s:
        j1 = queue.enqueue(s, kind="forecast", payload={"x": 1}, dedupe_key="forecast:abc")
        s.commit()
        first_id = j1.id
    with session_factory() as s:
        j2 = queue.enqueue(s, kind="forecast", payload={"x": 2}, dedupe_key="forecast:abc")
        s.commit()
        assert j2.id == first_id
    with session_factory() as s:
        # В БД ровно одно задание с этим ключом, payload — от первой постановки.
        assert s.scalar(select(func.count()).select_from(Job)) == 1
        assert s.scalar(select(Job.payload).where(Job.dedupe_key == "forecast:abc")) == {"x": 1}


def test_claim_marks_running_and_empty_queue_returns_none(session_factory) -> None:
    with session_factory() as s:
        queue.enqueue(s, kind="forecast", payload={})
        s.commit()
    with session_factory() as s:
        job = queue.claim_next(s, worker_id="w1", lease_seconds=300)
        assert job is not None
        assert job.status == "running"
        assert job.attempts == 1
        assert job.locked_by == "w1"
        s.commit()
    with session_factory() as s:
        # Второй worker видит пустую очередь (единственное задание уже в работе с живым lease).
        assert queue.claim_next(s, worker_id="w2", lease_seconds=300) is None
        s.commit()


def test_expired_lease_is_reclaimed(session_factory) -> None:
    with session_factory() as s:
        queue.enqueue(s, kind="forecast", payload={})
        s.commit()
    with session_factory() as s:
        job = queue.claim_next(s, worker_id="dead", lease_seconds=300)
        job_id = job.id
        s.commit()
    # Симулируем смерть worker: lease протух.
    with session_factory() as s:
        s.get(Job, job_id).lease_until = datetime.now(UTC) - timedelta(seconds=10)
        s.commit()
    with session_factory() as s:
        reclaimed = queue.claim_next(s, worker_id="alive", lease_seconds=300)
        assert reclaimed is not None
        assert reclaimed.id == job_id
        assert reclaimed.attempts == 2  # вторая попытка
        assert reclaimed.locked_by == "alive"
        s.commit()


def test_failed_job_retries_then_fails(session_factory) -> None:
    with session_factory() as s:
        queue.enqueue(s, kind="forecast", payload={}, max_attempts=2)
        s.commit()
    # Попытка 1 → провал → снова pending (retry_in_seconds=0, сразу готово).
    with session_factory() as s:
        job = queue.claim_next(s, worker_id="w", lease_seconds=300)
        queue.mark_failed(s, job, error_code="BoomError", retry_in_seconds=0)
        s.commit()
        assert job.status == "pending"
        assert job.last_error == "BoomError"
    # Попытка 2 → провал → окончательно failed (попытки исчерпаны).
    with session_factory() as s:
        job = queue.claim_next(s, worker_id="w", lease_seconds=300)
        assert job is not None
        assert job.attempts == 2
        queue.mark_failed(s, job, error_code="BoomError", retry_in_seconds=0)
        s.commit()
        assert job.status == "failed"
    # Больше не выдаётся: попытки исчерпаны.
    with session_factory() as s:
        assert queue.claim_next(s, worker_id="w", lease_seconds=300) is None
        s.commit()

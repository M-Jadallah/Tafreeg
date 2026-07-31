from __future__ import annotations

import threading
import time
from datetime import datetime

from celery import signals
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import WorkerStatus
from app.core.models import Job, WorkerState, utcnow

settings = get_settings()
_stop = threading.Event()
_thread: threading.Thread | None = None


def _upsert_worker(status: str, current_job_id: str | None = None, stage: str | None = None) -> None:
    if settings.worker_name in {"api", "scheduler"}:
        return
    try:
        with SessionLocal() as db:
            worker = db.get(WorkerState, settings.worker_name)
            if worker is None:
                worker = WorkerState(
                    name=settings.worker_name,
                    status=status,
                    started_at=utcnow(),
                )
                db.add(worker)
            worker.status = status
            worker.current_job_id = current_job_id
            worker.current_stage = stage
            worker.last_heartbeat_at = utcnow()
            worker.updated_at = utcnow()
            db.commit()
    except Exception:
        # A heartbeat failure must never terminate a worker.
        return


def _heartbeat_loop() -> None:
    while not _stop.wait(15):
        try:
            with SessionLocal() as db:
                worker = db.get(WorkerState, settings.worker_name)
                if worker is None:
                    worker = WorkerState(
                        name=settings.worker_name,
                        status=WorkerStatus.IDLE.value,
                        started_at=utcnow(),
                    )
                    db.add(worker)
                now = utcnow()
                worker.last_heartbeat_at = now
                if worker.status == WorkerStatus.OFFLINE.value:
                    worker.status = WorkerStatus.IDLE.value
                if worker.current_job_id:
                    job = db.get(Job, worker.current_job_id)
                    if job and job.locked_by == settings.worker_name:
                        from datetime import timedelta
                        job.last_heartbeat_at = now
                        job.lease_expires_at = now + timedelta(minutes=5)
                db.commit()
        except Exception:
            time.sleep(2)


@signals.worker_ready.connect
def worker_ready(**_: object) -> None:
    global _thread
    _upsert_worker(WorkerStatus.IDLE.value)
    _stop.clear()
    _thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="worker-heartbeat")
    _thread.start()


@signals.worker_shutdown.connect
def worker_shutdown(**_: object) -> None:
    _stop.set()
    _upsert_worker(WorkerStatus.OFFLINE.value)


@signals.task_prerun.connect
def task_prerun(task_id: str | None = None, task=None, args=None, kwargs=None, **_: object) -> None:
    job_id = None
    if kwargs and isinstance(kwargs, dict):
        job_id = kwargs.get("job_id") or kwargs.get("batch_id")
    elif args:
        job_id = args[0]
    _upsert_worker(WorkerStatus.BUSY.value, str(job_id) if job_id else None, getattr(task, "name", None))


@signals.task_postrun.connect
def task_postrun(**_: object) -> None:
    _upsert_worker(WorkerStatus.IDLE.value)


@signals.task_failure.connect
def task_failure(exception=None, **_: object) -> None:
    try:
        with SessionLocal() as db:
            worker = db.get(WorkerState, settings.worker_name)
            if worker:
                worker.last_error = str(exception)[:4000] if exception else "Task failure"
                worker.status = WorkerStatus.DEGRADED.value
                worker.last_heartbeat_at = utcnow()
                db.commit()
    except Exception:
        return

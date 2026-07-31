from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import JobStatus
from app.core.models import Batch, Job, JobEvent, utcnow

ACTIVE_STATUSES = {
    JobStatus.FETCHING_METADATA.value,
    JobStatus.CLAIMED.value,
    JobStatus.DOWNLOADING.value,
    JobStatus.TRANSCODING.value,
    JobStatus.AUDIO_READY.value,
    JobStatus.TRANSCRIBING.value,
    JobStatus.PARSING_RESPONSE.value,
    JobStatus.SAVING_TRANSCRIPT.value,
    JobStatus.GENERATING_EXPORTS.value,
    JobStatus.CANCEL_REQUESTED.value,
}
TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELED.value,
}


def set_job_state(
    db: Session,
    job: Job,
    status: str,
    *,
    message: str | None = None,
    progress: float | None = None,
    event_type: str = "state_changed",
    metadata: dict[str, Any] | None = None,
) -> None:
    previous = job.status
    job.status = status
    job.current_stage = status
    if progress is not None:
        job.progress = max(0.0, min(float(progress), 100.0))
    if job.started_at is None and status not in {JobStatus.CREATED.value, JobStatus.QUEUED.value}:
        job.started_at = utcnow()
    if status == JobStatus.COMPLETED.value:
        job.completed_at = utcnow()
        job.progress = 100.0
    db.add(
        JobEvent(
            job_id=job.id,
            event_type=event_type,
            previous_status=previous,
            new_status=status,
            message=message,
            event_metadata=metadata or {},
        )
    )
    db.commit()


def add_event(
    db: Session,
    job: Job,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        JobEvent(
            job_id=job.id,
            event_type=event_type,
            previous_status=job.status,
            new_status=job.status,
            message=message,
            event_metadata=metadata or {},
        )
    )
    db.commit()


def acquire_job_lease(db: Session, job_id: str, worker_name: str, minutes: int = 30) -> Job | None:
    job = db.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
    if job is None:
        return None
    now = utcnow()
    if (
        job.locked_by
        and job.locked_by != worker_name
        and job.lease_expires_at
        and job.lease_expires_at > now
    ):
        return None
    job.locked_by = worker_name
    job.worker_name = worker_name
    job.lease_started_at = now
    job.lease_expires_at = now + timedelta(minutes=minutes)
    job.last_heartbeat_at = now
    db.commit()
    db.refresh(job)
    return job


def refresh_job_lease(db: Session, job: Job, minutes: int = 30) -> None:
    now = utcnow()
    job.last_heartbeat_at = now
    job.lease_expires_at = now + timedelta(minutes=minutes)
    db.commit()


def release_job_lease(db: Session, job: Job) -> None:
    job.locked_by = None
    job.lease_expires_at = None
    job.last_heartbeat_at = utcnow()
    db.commit()


def ensure_not_canceled(job: Job) -> None:
    from app.services.errors import TaskCanceled

    if job.cancel_requested or job.status in {
        JobStatus.CANCEL_REQUESTED.value,
        JobStatus.CANCELED.value,
    }:
        raise TaskCanceled()


def increment_stage_retry(db: Session, job: Job, stage: str) -> int:
    counts = dict(job.stage_retry_counts or {})
    counts[stage] = int(counts.get(stage, 0)) + 1
    job.stage_retry_counts = counts
    job.retry_count += 1
    db.commit()
    return counts[stage]


def reset_job_for_retry(db: Session, job: Job, *, restart: bool = False) -> None:
    previous_status = job.status
    job.cancel_requested = False
    job.last_error_code = None
    job.last_error_message = None
    job.locked_by = None
    job.lease_expires_at = None
    job.worker_name = None
    job.completed_at = None
    if restart:
        job.progress = 0
        job.stage_retry_counts = {}
        job.status = JobStatus.QUEUED.value
        job.current_stage = JobStatus.QUEUED.value
    elif job.transcript:
        job.status = JobStatus.GENERATING_EXPORTS.value
        job.current_stage = JobStatus.GENERATING_EXPORTS.value
    elif any(a.deleted_at is None for a in job.audio_artifacts):
        job.status = JobStatus.AUDIO_READY.value
        job.current_stage = JobStatus.AUDIO_READY.value
    else:
        job.status = JobStatus.QUEUED.value
        job.current_stage = JobStatus.QUEUED.value
    db.add(
        JobEvent(
            job_id=job.id,
            event_type="manual_retry",
            previous_status=previous_status,
            new_status=job.status,
            message="تمت إعادة المهمة إلى الطابور يدويًا",
            event_metadata={"restart": restart},
        )
    )
    db.commit()


def refresh_batch_counts(db: Session, batch_id: str) -> None:
    batch = db.get(Batch, batch_id)
    if batch is None:
        return
    counts = dict(
        db.execute(
            select(Job.status, func.count(Job.id)).where(Job.batch_id == batch_id).group_by(Job.status)
        ).all()
    )
    batch.total_jobs = sum(counts.values())
    batch.completed_jobs = counts.get(JobStatus.COMPLETED.value, 0)
    batch.failed_jobs = counts.get(JobStatus.FAILED.value, 0)
    if batch.total_jobs and batch.completed_jobs == batch.total_jobs:
        batch.status = JobStatus.COMPLETED.value
    elif batch.failed_jobs and batch.completed_jobs + batch.failed_jobs == batch.total_jobs:
        batch.status = JobStatus.FAILED.value
    elif any(status in ACTIVE_STATUSES for status in counts):
        batch.status = JobStatus.CLAIMED.value
    else:
        batch.status = JobStatus.QUEUED.value
    db.commit()

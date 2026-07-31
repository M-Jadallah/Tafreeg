from __future__ import annotations

import logging
import shutil
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import JobStatus, WorkerStatus
from app.core.models import AudioArtifact, Job, WorkerState, utcnow
from app.services.job_service import ACTIVE_STATUSES, set_job_state
from app.services.log_service import write_exception, write_log
from app.services.settings_service import get_all_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("scheduler")
_last_disk_log_at: float = 0.0


def cleanup_audio() -> None:
    with SessionLocal() as db:
        now = utcnow()
        artifacts = db.execute(
            select(AudioArtifact).where(
                AudioArtifact.deleted_at.is_(None),
                AudioArtifact.delete_after.is_not(None),
                AudioArtifact.delete_after <= now,
            )
        ).scalars().all()
        for artifact in artifacts:
            job = db.get(Job, artifact.job_id)
            if job and job.status in ACTIVE_STATUSES:
                continue
            path = Path(artifact.file_path)
            try:
                if path.exists():
                    shutil.rmtree(path.parent, ignore_errors=False)
                artifact.deleted_at = now
                db.commit()
                write_log(
                    db,
                    service="scheduler",
                    job_id=artifact.job_id,
                    stage="audio_cleanup",
                    message=f"حُذف الملف الصوتي المؤقت بعد {settings.audio_retention_hours} ساعة",
                )
            except Exception as exc:
                db.rollback()
                write_exception(
                    db,
                    exc,
                    service="scheduler",
                    job_id=artifact.job_id,
                    stage="audio_cleanup",
                    error_code="AUDIO_CLEANUP_FAILED",
                    message="فشل حذف ملف صوتي مؤقت وسيعاد لاحقًا",
                    retryable=True,
                )


def recover_stale_jobs() -> None:
    with SessionLocal() as db:
        now = utcnow()
        jobs = db.execute(
            select(Job).where(
                Job.status.in_(ACTIVE_STATUSES),
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < now,
            )
        ).scalars().all()
        if not jobs:
            return
        from app.workers.tasks import process_job

        for job in jobs:
            old_worker = job.locked_by
            job.locked_by = None
            job.lease_expires_at = None
            job.worker_name = None
            set_job_state(
                db,
                job,
                JobStatus.QUEUED.value,
                message="استعاد النظام المهمة بعد انقطاع العامل",
                event_type="worker_recovery",
                metadata={"previous_worker": old_worker},
            )
            process_job.delay(job_id=job.id)


def mark_offline_workers() -> None:
    with SessionLocal() as db:
        cutoff = utcnow() - timedelta(seconds=60)
        workers = db.execute(select(WorkerState)).scalars().all()
        for worker in workers:
            if not worker.last_heartbeat_at or worker.last_heartbeat_at < cutoff:
                worker.status = WorkerStatus.OFFLINE.value
                worker.current_job_id = None
                worker.current_stage = None
        db.commit()


def cleanup_orphans() -> None:
    cutoff = time.time() - settings.audio_retention_hours * 3600
    settings.audio_root.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        known = {Path(p).parent for p in db.execute(select(AudioArtifact.file_path)).scalars()}
    for child in settings.audio_root.iterdir():
        try:
            if child.is_dir() and child not in known and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue



def check_disk_usage() -> None:
    global _last_disk_log_at
    now_ts = time.time()
    if now_ts - _last_disk_log_at < 3600:
        return
    with SessionLocal() as db:
        app_settings = get_all_settings(db)
        usage = shutil.disk_usage(settings.audio_root)
        percent = round(usage.used / usage.total * 100, 1)
        warning = float(app_settings["disk_warning_percent"])
        critical = float(app_settings["disk_critical_percent"])
        if percent >= warning:
            write_log(
                db,
                level="critical" if percent >= critical else "warning",
                service="scheduler",
                stage="disk_monitoring",
                error_code="DISK_SPACE_CRITICAL" if percent >= critical else "DISK_SPACE_LOW",
                message=f"استخدام مساحة القرص بلغ {percent}%",
                technical_details=f"used={usage.used}; total={usage.total}; free={usage.free}",
            )
            _last_disk_log_at = now_ts

def _write_heartbeat() -> None:
    heartbeat = Path("/tmp/scheduler-heartbeat")
    heartbeat.write_text(utcnow().isoformat(), encoding="utf-8")


def run_once() -> None:
    cleanup_audio()
    recover_stale_jobs()
    mark_offline_workers()
    cleanup_orphans()
    check_disk_usage()
    _write_heartbeat()


def main() -> None:
    logger.info("Scheduler started")
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Scheduler cycle failed")
        time.sleep(60)


if __name__ == "__main__":
    main()

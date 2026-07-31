from __future__ import annotations

import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import AttemptStatus, BatchType, ChunkStatus, JobStatus, WorkerStatus
from app.core.models import (
    AudioArtifact,
    Batch,
    Job,
    JobAttempt,
    Transcript,
    TranscriptChunk,
    WorkerState,
    utcnow,
)
from app.services.audio_service import (
    create_audio_artifact,
    ensure_chunk_audio,
    probe_audio,
    split_audio,
    transcode_audio,
)
from app.services.deepgram_service import extract_transcript_payload, transcribe_file
from app.services.errors import TaskCanceled, WorkflowError
from app.services.export_service import ensure_exports
from app.services.job_service import (
    acquire_job_lease,
    ensure_not_canceled,
    increment_stage_retry,
    refresh_batch_counts,
    refresh_job_lease,
    release_job_lease,
    set_job_state,
)
from app.services.log_service import write_exception, write_log
from app.services.settings_service import get_all_settings
from app.services.youtube_service import (
    detect_source_type,
    download_audio_source,
    extract_info_with_cookie_fallback,
)

settings = get_settings()


class WorkflowTask(Task):
    autoretry_for = ()
    acks_late = True
    reject_on_worker_lost = True


def _retry_delay(app_settings: dict[str, Any], attempt: int) -> int:
    initial = int(app_settings["retry_initial_seconds"])
    multiplier = float(app_settings["retry_multiplier"])
    maximum = int(app_settings["retry_max_seconds"])
    jitter = int(app_settings["retry_jitter_seconds"])
    delay = min(maximum, int(initial * (multiplier ** max(0, attempt - 1))))
    return delay + random.randint(0, max(0, jitter))


def _stage_max_retries(app_settings: dict[str, Any], stage: str) -> int:
    mapping = {
        JobStatus.FETCHING_METADATA.value: "metadata_max_retries",
        JobStatus.DOWNLOADING.value: "download_max_retries",
        JobStatus.TRANSCODING.value: "transcode_max_retries",
        JobStatus.TRANSCRIBING.value: "deepgram_max_retries",
        JobStatus.GENERATING_EXPORTS.value: "export_max_retries",
    }
    return int(app_settings.get(mapping.get(stage, "deepgram_max_retries"), 3))


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _mark_worker_result(db: Session, success: bool, error: str | None = None) -> None:
    worker = db.get(WorkerState, settings.worker_name)
    if worker is None:
        return
    if success:
        worker.successful_jobs += 1
        worker.last_error = None
    else:
        worker.failed_jobs += 1
        worker.last_error = error[:4000] if error else None
    db.commit()


@celery_app.task(bind=True, base=WorkflowTask, name="workflow.expand_source")
def expand_source(self: WorkflowTask, batch_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        batch = db.get(Batch, batch_id)
        if batch is None:
            return {"status": "missing"}
        app_settings = get_all_settings(db)
        batch.status = JobStatus.FETCHING_METADATA.value
        db.commit()
        try:
            source_type = detect_source_type(batch.source_url)
            info = extract_info_with_cookie_fallback(
                batch.source_url,
                flat_playlist=source_type == BatchType.PLAYLIST.value,
                timeout=int(app_settings["metadata_timeout_seconds"]),
            )
            batch.source_type = source_type
            batch.youtube_playlist_id = info.get("id") if source_type == "playlist" else None
            batch.title = info.get("title")
            entries = info.get("entries") or []
            if source_type == "video":
                entries = [info]
            if not entries:
                raise WorkflowError("YT_PLAYLIST_EMPTY", "قائمة التشغيل فارغة أو لا تحتوي فيديوهات متاحة")
            created: list[str] = []
            for index, entry in enumerate(entries, start=1):
                if not entry:
                    continue
                video_id = entry.get("id")
                if not video_id:
                    continue
                existing = db.execute(
                    select(Job).where(Job.batch_id == batch.id, Job.youtube_video_id == video_id)
                ).scalar_one_or_none()
                if existing:
                    created.append(existing.id)
                    continue
                url = entry.get("webpage_url") or entry.get("url")
                if not isinstance(url, str) or not url.startswith("http"):
                    url = _video_url(video_id)
                job = Job(
                    batch_id=batch.id,
                    youtube_video_id=video_id,
                    source_url=url,
                    title=entry.get("title"),
                    channel=entry.get("channel") or entry.get("uploader"),
                    thumbnail_url=entry.get("thumbnail"),
                    duration_seconds=entry.get("duration"),
                    playlist_index=entry.get("playlist_index") or index,
                    status=JobStatus.QUEUED.value,
                    current_stage=JobStatus.QUEUED.value,
                    language=batch.language,
                    model=batch.model,
                    options=batch.options or {},
                )
                db.add(job)
                db.flush()
                created.append(job.id)
            batch.total_jobs = len(created)
            batch.status = JobStatus.QUEUED.value
            db.commit()
            for job_id in created:
                process_job.delay(job_id=job_id)
            write_log(
                db,
                service="worker",
                worker_name=settings.worker_name,
                batch_id=batch.id,
                message=f"تم إنشاء {len(created)} مهمة من رابط YouTube",
            )
            return {"status": "queued", "jobs": len(created)}
        except WorkflowError as exc:
            batch.status = (
                JobStatus.WAITING_FOR_COOKIES.value
                if exc.requires_cookies
                else JobStatus.FAILED.value
            )
            db.commit()
            write_log(
                db,
                level="error",
                service="worker",
                worker_name=settings.worker_name,
                batch_id=batch.id,
                stage=JobStatus.FETCHING_METADATA.value,
                error_code=exc.code,
                message=exc.user_message,
                technical_details=exc.technical_message,
                retryable=exc.retryable,
            )
            if exc.retryable and self.request.retries < int(app_settings["metadata_max_retries"]):
                delay = _retry_delay(app_settings, self.request.retries + 1)
                raise self.retry(exc=exc, countdown=delay, max_retries=int(app_settings["metadata_max_retries"]))
            return {"status": "failed", "error": exc.code}
        except Exception as exc:
            db.rollback()
            batch = db.get(Batch, batch_id) or batch
            max_retries = int(app_settings["metadata_max_retries"])
            retryable = self.request.retries < max_retries
            batch.status = JobStatus.RETRY_WAIT.value if retryable else JobStatus.FAILED.value
            db.commit()
            write_exception(
                db,
                exc,
                service="worker",
                worker_name=settings.worker_name,
                batch_id=batch.id,
                stage=JobStatus.FETCHING_METADATA.value,
                error_code="UNEXPECTED_EXPANSION_ERROR",
                message="حدث خطأ غير متوقع أثناء قراءة رابط YouTube",
                retryable=retryable,
            )
            if retryable:
                delay = _retry_delay(app_settings, self.request.retries + 1)
                raise self.retry(exc=exc, countdown=delay, max_retries=max_retries)
            return {"status": "failed"}


def _get_main_audio(job: Job) -> AudioArtifact | None:
    for artifact in job.audio_artifacts:
        if artifact.kind == "main" and artifact.deleted_at is None and Path(artifact.file_path).exists():
            return artifact
    return None


def _load_or_create_attempt(db: Session, job: Job) -> JobAttempt:
    attempt = JobAttempt(
        job_id=job.id,
        attempt_number=job.retry_count + 1,
        stage=job.current_stage,
        worker_name=settings.worker_name,
        status=AttemptStatus.RUNNING.value,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _finalize_success(db: Session, job: Job, attempt: JobAttempt) -> dict[str, Any]:
    """Create any missing exports and commit a successful terminal state."""
    set_job_state(
        db,
        job,
        JobStatus.GENERATING_EXPORTS.value,
        message="إنشاء Word وTXT وJSON",
        progress=95,
    )
    ensure_exports(db, job)
    set_job_state(db, job, JobStatus.COMPLETED.value, message="اكتملت المهمة بنجاح", progress=100)
    release_job_lease(db, job)
    attempt.status = AttemptStatus.SUCCESS.value
    attempt.stage = JobStatus.COMPLETED.value
    attempt.ended_at = utcnow()
    db.commit()
    _mark_worker_result(db, True)
    refresh_batch_counts(db, job.batch_id)
    write_log(
        db,
        service="worker",
        worker_name=settings.worker_name,
        job_id=job.id,
        batch_id=job.batch_id,
        stage=JobStatus.COMPLETED.value,
        message="اكتمل تفريغ الفيديو وإنشاء ملفات التصدير",
    )
    return {"status": "completed", "job_id": job.id}


def _merge_chunks(chunks: list[TranscriptChunk]) -> dict[str, Any]:
    texts: list[str] = []
    words: list[dict[str, Any]] = []
    utterances: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    request_ids: list[str] = []
    paragraphs: list[Any] = []
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        if chunk.transcript_text:
            texts.append(chunk.transcript_text.strip())
        response = chunk.raw_response_json or {}
        payload = extract_transcript_payload(response, chunk.offset_seconds)
        words.extend(payload["words"])
        utterances.extend(payload["utterances"])
        if payload["paragraphs"]:
            paragraphs.append(payload["paragraphs"])
        if payload["request_id"]:
            request_ids.append(str(payload["request_id"]))
        raw.append(response)
    return {
        "text": "\n\n".join(text for text in texts if text),
        "words": words,
        "utterances": utterances,
        "paragraphs": paragraphs,
        "raw": {"chunks": raw},
        "request_id": ",".join(request_ids)[:128] if request_ids else None,
    }


@celery_app.task(bind=True, base=WorkflowTask, name="workflow.process_job")
def process_job(self: WorkflowTask, job_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        job = acquire_job_lease(db, job_id, settings.worker_name)
        if job is None:
            return {"status": "locked_or_missing"}
        attempt = _load_or_create_attempt(db, job)
        app_settings = get_all_settings(db)
        try:
            ensure_not_canceled(job)

            # A saved transcript is the strongest checkpoint. Export retries must
            # never redownload audio that may already have been cleaned after 24 hours.
            if job.transcript is not None:
                return _finalize_success(db, job, attempt)

            if not job.title or not job.duration_seconds:
                set_job_state(db, job, JobStatus.FETCHING_METADATA.value, message="جلب معلومات الفيديو", progress=2)
                info = extract_info_with_cookie_fallback(
                    job.source_url,
                    flat_playlist=False,
                    timeout=int(app_settings["metadata_timeout_seconds"]),
                )
                job.youtube_video_id = job.youtube_video_id or info.get("id")
                job.title = info.get("title") or job.title
                job.channel = info.get("channel") or info.get("uploader") or job.channel
                job.thumbnail_url = info.get("thumbnail") or job.thumbnail_url
                job.duration_seconds = info.get("duration") or job.duration_seconds
                db.commit()

            ensure_not_canceled(job)
            audio = _get_main_audio(job)
            if audio is None:
                job_dir = settings.audio_root / job.id
                source_dir = job_dir / "source"
                set_job_state(db, job, JobStatus.DOWNLOADING.value, message="تنزيل الصوت من YouTube", progress=5)
                last_commit = {"value": -10.0}

                def update_progress(percent: float) -> None:
                    if percent - last_commit["value"] >= 2:
                        db.refresh(job)
                        ensure_not_canceled(job)
                        job.progress = 5 + (percent * 0.35)
                        refresh_job_lease(db, job)
                        last_commit["value"] = percent

                source = download_audio_source(
                    job.source_url,
                    source_dir,
                    timeout=int(app_settings["download_timeout_seconds"]),
                    progress_callback=update_progress,
                )
                ensure_not_canceled(job)
                set_job_state(db, job, JobStatus.TRANSCODING.value, message="تحويل الصوت إلى MP3 64K", progress=42)
                destination = job_dir / "audio.mp3"
                metadata = transcode_audio(
                    source,
                    destination,
                    bitrate=str(app_settings["audio_bitrate"]),
                    sample_rate=int(app_settings["audio_sample_rate"]),
                    channels=int(app_settings["audio_channels"]),
                    timeout=int(app_settings["ffmpeg_timeout_seconds"]),
                )
                shutil.rmtree(source_dir, ignore_errors=True)
                audio = create_audio_artifact(job, destination, metadata)
                audio.bitrate = str(app_settings["audio_bitrate"])
                db.add(audio)
                job.duration_seconds = metadata.get("duration") or job.duration_seconds
                db.commit()
                set_job_state(db, job, JobStatus.AUDIO_READY.value, message="الملف الصوتي جاهز", progress=48)
            else:
                refresh_job_lease(db, job)

            ensure_not_canceled(job)
            if job.transcript is None:
                set_job_state(db, job, JobStatus.TRANSCRIBING.value, message="إرسال الصوت إلى Deepgram", progress=50)
                audio_path = Path(audio.file_path)
                duration = float(audio.duration or job.duration_seconds or probe_audio(audio_path)["duration"])
                threshold = int(app_settings["long_audio_threshold_seconds"])
                if duration > threshold:
                    chunks = db.execute(
                        select(TranscriptChunk)
                        .where(TranscriptChunk.job_id == job.id)
                        .order_by(TranscriptChunk.chunk_index)
                    ).scalars().all()
                    if not chunks:
                        chunks = split_audio(
                            job,
                            audio_path,
                            duration=duration,
                            chunk_seconds=int(app_settings["chunk_duration_seconds"]),
                            timeout=int(app_settings["ffmpeg_timeout_seconds"]),
                        )
                        db.add_all(chunks)
                        db.commit()
                    total = len(chunks)
                    for position, chunk in enumerate(chunks, start=1):
                        ensure_not_canceled(job)
                        if chunk.status == ChunkStatus.COMPLETED.value and chunk.raw_response_json:
                            continue
                        chunk.status = ChunkStatus.TRANSCRIBING.value
                        db.commit()
                        chunk_path = ensure_chunk_audio(
                            audio_path, chunk, timeout=int(app_settings["ffmpeg_timeout_seconds"])
                        )
                        response = transcribe_file(
                            chunk_path,
                            api_key=settings.deepgram_api_key or "",
                            model=job.model,
                            language=job.language,
                            options=job.options or {},
                            timeout_seconds=int(app_settings["deepgram_timeout_seconds"]),
                        )
                        payload = extract_transcript_payload(response)
                        chunk.raw_response_json = response
                        chunk.transcript_text = payload["text"]
                        chunk.request_id = payload["request_id"]
                        chunk.status = ChunkStatus.COMPLETED.value
                        chunk.error_message = None
                        job.progress = 50 + (position / total) * 35
                        refresh_job_lease(db, job)
                        db.commit()
                    merged = _merge_chunks(chunks)
                else:
                    chunk = db.execute(
                        select(TranscriptChunk).where(
                            TranscriptChunk.job_id == job.id, TranscriptChunk.chunk_index == 0
                        )
                    ).scalar_one_or_none()
                    if chunk is None:
                        chunk = TranscriptChunk(
                            job_id=job.id, chunk_index=0, offset_seconds=0,
                            duration_seconds=duration, file_path=str(audio_path), status=ChunkStatus.READY.value
                        )
                        db.add(chunk)
                        db.commit()
                    if chunk.status != ChunkStatus.COMPLETED.value or not chunk.raw_response_json:
                        chunk.status = ChunkStatus.TRANSCRIBING.value
                        db.commit()
                        response = transcribe_file(
                            audio_path,
                            api_key=settings.deepgram_api_key or "",
                            model=job.model,
                            language=job.language,
                            options=job.options or {},
                            timeout_seconds=int(app_settings["deepgram_timeout_seconds"]),
                        )
                        payload = extract_transcript_payload(response)
                        chunk.raw_response_json = response
                        chunk.transcript_text = payload["text"]
                        chunk.request_id = payload["request_id"]
                        chunk.status = ChunkStatus.COMPLETED.value
                        db.commit()
                    merged = _merge_chunks([chunk])
                set_job_state(db, job, JobStatus.PARSING_RESPONSE.value, message="معالجة نتيجة Deepgram", progress=88)
                if not merged["text"]:
                    raise WorkflowError("DG_EMPTY_TRANSCRIPT", "أعاد Deepgram تفريغًا فارغًا", retryable=True)
                transcript = Transcript(
                    job_id=job.id,
                    provider="deepgram",
                    model=job.model,
                    language=job.language,
                    full_text=merged["text"],
                    paragraphs_json=merged["paragraphs"],
                    utterances_json=merged["utterances"],
                    words_json=merged["words"],
                    raw_response_json=merged["raw"],
                    request_id=merged["request_id"],
                )
                db.add(transcript)
                db.commit()
                db.refresh(job)
                set_job_state(db, job, JobStatus.SAVING_TRANSCRIPT.value, message="تم حفظ التفريغ", progress=92)

            ensure_not_canceled(job)
            return _finalize_success(db, job, attempt)

        except TaskCanceled:
            set_job_state(db, job, JobStatus.CANCELED.value, message="ألغى المستخدم المهمة")
            release_job_lease(db, job)
            attempt.status = AttemptStatus.CANCELED.value
            attempt.ended_at = utcnow()
            db.commit()
            refresh_batch_counts(db, job.batch_id)
            return {"status": "canceled"}
        except WorkflowError as exc:
            stage = job.current_stage
            attempt.stage = stage
            attempt.error_code = exc.code
            attempt.error_details = exc.technical_message or exc.user_message
            attempt.ended_at = utcnow()
            job.last_error_code = exc.code
            job.last_error_message = exc.user_message
            write_log(
                db,
                level="error",
                service="worker",
                worker_name=settings.worker_name,
                job_id=job.id,
                batch_id=job.batch_id,
                stage=stage,
                error_code=exc.code,
                message=exc.user_message,
                technical_details=exc.technical_message,
                retryable=exc.retryable,
            )
            if exc.requires_cookies:
                attempt.status = AttemptStatus.FAILED.value
                set_job_state(db, job, JobStatus.WAITING_FOR_COOKIES.value, message=exc.user_message)
                release_job_lease(db, job)
                db.commit()
                _mark_worker_result(db, False, exc.user_message)
                refresh_batch_counts(db, job.batch_id)
                return {"status": "waiting_for_cookies", "error": exc.code}
            retry_number = increment_stage_retry(db, job, stage)
            max_retries = _stage_max_retries(app_settings, stage)
            if exc.retryable and retry_number <= max_retries:
                attempt.status = AttemptStatus.RETRYING.value
                delay = _retry_delay(app_settings, retry_number)
                set_job_state(
                    db,
                    job,
                    JobStatus.RETRY_WAIT.value,
                    message=f"ستعاد المحاولة تلقائيًا بعد {delay} ثانية",
                    event_type="retry_scheduled",
                    metadata={"error_code": exc.code, "retry": retry_number, "delay": delay},
                )
                release_job_lease(db, job)
                db.commit()
                raise self.retry(exc=exc, countdown=delay, max_retries=100)
            attempt.status = AttemptStatus.FAILED.value
            set_job_state(db, job, JobStatus.FAILED.value, message=exc.user_message)
            release_job_lease(db, job)
            db.commit()
            _mark_worker_result(db, False, exc.user_message)
            refresh_batch_counts(db, job.batch_id)
            return {"status": "failed", "error": exc.code}
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id) or job
            attempt = db.get(JobAttempt, attempt.id) or attempt
            stage = job.current_stage
            attempt.error_code = "UNEXPECTED_WORKFLOW_ERROR"
            attempt.error_details = str(exc)
            attempt.ended_at = utcnow()
            job.last_error_code = "UNEXPECTED_WORKFLOW_ERROR"
            job.last_error_message = "حدث خطأ غير متوقع داخل العامل"
            retry_number = increment_stage_retry(db, job, stage)
            max_retries = _stage_max_retries(app_settings, stage)
            retryable = retry_number <= max_retries
            write_exception(
                db,
                exc,
                service="worker",
                worker_name=settings.worker_name,
                job_id=job.id,
                batch_id=job.batch_id,
                stage=stage,
                error_code="UNEXPECTED_WORKFLOW_ERROR",
                message="حدث خطأ غير متوقع داخل العامل",
                retryable=retryable,
            )
            if retryable:
                attempt.status = AttemptStatus.RETRYING.value
                delay = _retry_delay(app_settings, retry_number)
                set_job_state(
                    db,
                    job,
                    JobStatus.RETRY_WAIT.value,
                    message=f"حدث خطأ غير متوقع؛ ستعاد المحاولة بعد {delay} ثانية",
                    event_type="unexpected_retry_scheduled",
                    metadata={"retry": retry_number, "delay": delay},
                )
                release_job_lease(db, job)
                db.commit()
                raise self.retry(exc=exc, countdown=delay, max_retries=100)
            attempt.status = AttemptStatus.FAILED.value
            set_job_state(db, job, JobStatus.FAILED.value, message=job.last_error_message)
            release_job_lease(db, job)
            db.commit()
            _mark_worker_result(db, False, str(exc))
            refresh_batch_counts(db, job.batch_id)
            return {"status": "failed", "error": "UNEXPECTED_WORKFLOW_ERROR"}

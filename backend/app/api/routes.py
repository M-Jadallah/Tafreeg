from __future__ import annotations

import asyncio
import csv
import io
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from redis import Redis

from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import JobStatus, LogLevel, WorkerStatus
from app.core.models import AppSetting, Batch, ExportArtifact, Job, SystemLog, WorkerState, utcnow
from app.core.schemas import (
    BatchOut,
    BulkDeleteRequest,
    CookieStatus,
    CreateBatchRequest,
    DashboardOut,
    JobDetailOut,
    JobSummaryOut,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PaginatedJobs,
    PaginatedLogs,
    SettingsPayload,
    WorkerOut,
)
from app.core.security import (
    check_login_rate_limit,
    clear_auth_cookies,
    clear_login_failures,
    get_client_ip,
    record_login_failure,
    require_admin,
    require_csrf,
    revoke_session_token,
    set_auth_cookies,
    verify_credentials,
)
from app.services.export_service import ensure_exports
from app.services.job_service import ACTIVE_STATUSES, refresh_batch_counts, reset_job_for_retry, set_job_state
from app.services.log_service import audit, write_log
from app.services.settings_service import get_all_settings, update_settings
from app.services.youtube_service import cookie_status, extract_info, save_cookies, validate_youtube_url
from app.workers.tasks import expand_source, process_job

settings = get_settings()
router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[str, Depends(require_admin)]
CsrfAdmin = Annotated[str, Depends(require_csrf)]


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Db) -> LoginResponse:
    ip = get_client_ip(request)
    check_login_rate_limit(ip)
    if not verify_credentials(payload.username, payload.password):
        record_login_failure(ip)
        write_log(db, level="warning", service="auth", message="محاولة تسجيل دخول فاشلة")
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
    clear_login_failures(ip)
    set_auth_cookies(response, payload.username)
    audit(db, action="login", actor=payload.username, ip_address=ip)
    return LoginResponse(username=payload.username)


@router.post("/auth/logout", response_model=MessageResponse)
def logout(response: Response, request: Request, db: Db, admin: CsrfAdmin) -> MessageResponse:
    revoke_session_token(request.cookies.get("yt_session"))
    clear_auth_cookies(response)
    audit(db, action="logout", actor=admin, ip_address=get_client_ip(request))
    return MessageResponse(message="تم تسجيل الخروج")


@router.get("/auth/me")
def me(admin: Admin) -> dict[str, Any]:
    return {"authenticated": True, "username": admin}


@router.post("/batches", response_model=BatchOut, status_code=202)
def create_batch(payload: CreateBatchRequest, request: Request, db: Db, admin: CsrfAdmin) -> Batch:
    url = validate_youtube_url(str(payload.url))
    runtime_settings = get_all_settings(db)
    usage = shutil.disk_usage(settings.audio_root)
    used_percent = usage.used / usage.total * 100
    if used_percent >= float(runtime_settings["disk_critical_percent"]):
        raise HTTPException(507, "مساحة القرص بلغت الحد الحرج. احذف ملفات غير مطلوبة أو زد المساحة.")
    batch = Batch(
        source_url=url,
        language=payload.language,
        model=payload.model,
        options={
            "paragraphs": payload.paragraphs,
            "utterances": payload.utterances,
            "punctuate": payload.punctuate,
            "smart_format": payload.smart_format,
        },
        status=JobStatus.CREATED.value,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    expand_source.delay(batch_id=batch.id)
    audit(
        db,
        action="create_batch",
        actor=admin,
        target_type="batch",
        target_id=batch.id,
        details={"url": url},
        ip_address=get_client_ip(request),
    )
    return batch


@router.get("/batches", response_model=list[BatchOut])
def list_batches(db: Db, _: Admin, limit: int = Query(50, ge=1, le=200)) -> list[Batch]:
    return list(db.execute(select(Batch).order_by(Batch.created_at.desc()).limit(limit)).scalars())


@router.delete("/batches/{batch_id}", response_model=MessageResponse)
def delete_batch(batch_id: str, db: Db, admin: CsrfAdmin) -> MessageResponse:
    batch = db.execute(
        select(Batch).where(Batch.id == batch_id).options(
            selectinload(Batch.jobs).selectinload(Job.audio_artifacts),
            selectinload(Batch.jobs).selectinload(Job.exports),
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "قائمة التشغيل غير موجودة")
    if any(job.status in ACTIVE_STATUSES for job in batch.jobs):
        raise HTTPException(409, "توجد مهام نشطة داخل القائمة")
    for job in batch.jobs:
        _delete_job_files(job)
    db.delete(batch)
    db.commit()
    audit(db, action="delete_batch", actor=admin, target_type="batch", target_id=batch_id)
    return MessageResponse(message="حُذفت القائمة وجميع تفريغاتها")


@router.get("/jobs", response_model=PaginatedJobs)
def list_jobs(
    db: Db,
    _: Admin,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=10, le=100),
    status_value: str | None = Query(None, alias="status"),
    worker: str | None = None,
    batch_id: str | None = None,
    search: str | None = None,
) -> PaginatedJobs:
    query = select(Job)
    count_query = select(func.count(Job.id))
    conditions = []
    if status_value:
        conditions.append(Job.status == status_value)
    if worker:
        conditions.append(Job.worker_name == worker)
    if batch_id:
        conditions.append(Job.batch_id == batch_id)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(Job.title.ilike(pattern), Job.youtube_video_id.ilike(pattern), Job.channel.ilike(pattern))
        )
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    total = db.execute(count_query).scalar_one()
    items = list(
        db.execute(
            query.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        ).scalars()
    )
    return PaginatedJobs(items=items, total=total, page=page, page_size=page_size)


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: Db, _: Admin) -> Job:
    job = db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.transcript),
            selectinload(Job.events),
            selectinload(Job.attempts),
            selectinload(Job.exports),
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    job.events.sort(key=lambda item: item.created_at, reverse=True)
    job.attempts.sort(key=lambda item: item.started_at, reverse=True)
    return job


@router.post("/jobs/{job_id}/retry", response_model=MessageResponse)
def retry_job(job_id: str, db: Db, admin: CsrfAdmin) -> MessageResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    if job.status in ACTIVE_STATUSES or job.status in {JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value}:
        raise HTTPException(409, "المهمة تعمل أو تنتظر التنفيذ حاليًا")
    reset_job_for_retry(db, job, restart=False)
    process_job.delay(job_id=job.id)
    audit(db, action="retry_job", actor=admin, target_type="job", target_id=job.id)
    return MessageResponse(message="تمت إعادة المهمة إلى الطابور")


@router.post("/jobs/{job_id}/restart", response_model=MessageResponse)
def restart_job(job_id: str, db: Db, admin: CsrfAdmin) -> MessageResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    if job.status in ACTIVE_STATUSES or job.status in {JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value}:
        raise HTTPException(409, "المهمة تعمل أو تنتظر التنفيذ حاليًا")
    # Force the pipeline to recreate all products from the source.
    if job.transcript:
        db.delete(job.transcript)
    for export in list(job.exports):
        Path(export.file_path).unlink(missing_ok=True)
        db.delete(export)
    for artifact in list(job.audio_artifacts):
        if Path(artifact.file_path).exists():
            shutil.rmtree(Path(artifact.file_path).parent, ignore_errors=True)
        db.delete(artifact)
    for chunk in list(job.chunks):
        db.delete(chunk)
    db.commit()
    reset_job_for_retry(db, job, restart=True)
    process_job.delay(job_id=job.id)
    audit(db, action="restart_job", actor=admin, target_type="job", target_id=job.id)
    return MessageResponse(message="ستبدأ المهمة من جديد")


@router.post("/jobs/{job_id}/cancel", response_model=MessageResponse)
def cancel_job(job_id: str, db: Db, admin: CsrfAdmin) -> MessageResponse:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    cancellable = ACTIVE_STATUSES | {JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value}
    if job.status not in cancellable:
        raise HTTPException(409, "لا يمكن إلغاء المهمة في حالتها الحالية")
    job.cancel_requested = True
    if job.status in {JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value} and not job.locked_by:
        set_job_state(db, job, JobStatus.CANCELED.value, message="ألغى المستخدم المهمة قبل بدء التنفيذ")
        refresh_batch_counts(db, job.batch_id)
        message = "تم إلغاء المهمة"
    else:
        set_job_state(db, job, JobStatus.CANCEL_REQUESTED.value, message="طلب المستخدم إلغاء المهمة")
        message = "تم إرسال طلب الإلغاء"
    audit(db, action="cancel_job", actor=admin, target_type="job", target_id=job.id)
    return MessageResponse(message=message)


def _delete_job_files(job: Job) -> None:
    for artifact in job.audio_artifacts:
        path = Path(artifact.file_path)
        if path.exists():
            shutil.rmtree(path.parent, ignore_errors=True)
    for export in job.exports:
        Path(export.file_path).unlink(missing_ok=True)
    export_dir = settings.exports_root / job.id
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)


@router.delete("/jobs/{job_id}", response_model=MessageResponse)
def delete_job(job_id: str, db: Db, admin: CsrfAdmin) -> MessageResponse:
    job = db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.audio_artifacts), selectinload(Job.exports))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "المهمة غير موجودة")
    if job.status in ACTIVE_STATUSES or job.status == JobStatus.CANCEL_REQUESTED.value:
        raise HTTPException(409, "يجب إلغاء المهمة النشطة قبل حذفها")
    _delete_job_files(job)
    target = job.id
    db.delete(job)
    db.commit()
    audit(db, action="delete_job", actor=admin, target_type="job", target_id=target)
    return MessageResponse(message="حُذفت المهمة وملفاتها نهائيًا")


@router.post("/jobs/bulk-delete", response_model=MessageResponse)
def bulk_delete_jobs(payload: BulkDeleteRequest, db: Db, admin: CsrfAdmin) -> MessageResponse:
    jobs = list(
        db.execute(
            select(Job)
            .where(Job.id.in_(payload.job_ids))
            .options(selectinload(Job.audio_artifacts), selectinload(Job.exports))
        ).scalars()
    )
    active = [job.id for job in jobs if job.status in ACTIVE_STATUSES]
    if active:
        raise HTTPException(409, detail={"message": "توجد مهام نشطة", "job_ids": active})
    for job in jobs:
        _delete_job_files(job)
        db.delete(job)
    db.commit()
    audit(db, action="bulk_delete_jobs", actor=admin, details={"count": len(jobs)})
    return MessageResponse(message=f"حُذفت {len(jobs)} مهمة")


@router.get("/jobs/{job_id}/export/{format_name}")
def download_export(job_id: str, format_name: str, db: Db, _: Admin) -> FileResponse:
    if format_name not in {"docx", "txt", "json"}:
        raise HTTPException(400, "صيغة غير مدعومة")
    job = db.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.transcript), selectinload(Job.exports))
    ).scalar_one_or_none()
    if not job or not job.transcript:
        raise HTTPException(404, "التفريغ غير موجود")
    ensure_exports(db, job)
    artifact = db.execute(
        select(ExportArtifact).where(
            ExportArtifact.job_id == job_id, ExportArtifact.format == format_name
        )
    ).scalar_one()
    path = Path(artifact.file_path)
    if not path.exists():
        raise HTTPException(404, "ملف التصدير غير موجود")
    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json",
    }
    return FileResponse(path, media_type=media_types[format_name], filename=path.name)


@router.get("/workers", response_model=list[WorkerOut])
def list_workers(db: Db, _: Admin) -> list[WorkerState]:
    return list(db.execute(select(WorkerState).order_by(WorkerState.name)).scalars())


@router.get("/logs", response_model=PaginatedLogs)
def list_logs(
    db: Db,
    _: Admin,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    level: str | None = None,
    worker: str | None = None,
    job_id: str | None = None,
    stage: str | None = None,
    search: str | None = None,
) -> PaginatedLogs:
    query = select(SystemLog)
    count_query = select(func.count(SystemLog.id))
    conditions = []
    if level:
        conditions.append(SystemLog.level == level)
    if worker:
        conditions.append(SystemLog.worker_name == worker)
    if job_id:
        conditions.append(SystemLog.job_id == job_id)
    if stage:
        conditions.append(SystemLog.stage == stage)
    if search:
        pattern = f"%{search}%"
        conditions.append(or_(SystemLog.message.ilike(pattern), SystemLog.error_code.ilike(pattern)))
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    total = db.execute(count_query).scalar_one()
    items = list(
        db.execute(
            query.order_by(SystemLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return PaginatedLogs(items=items, total=total, page=page, page_size=page_size)


@router.delete("/logs", response_model=MessageResponse)
def clear_logs(db: Db, admin: CsrfAdmin) -> MessageResponse:
    count = db.query(SystemLog).delete(synchronize_session=False)
    db.commit()
    audit(db, action="clear_logs", actor=admin, details={"count": count})
    return MessageResponse(message=f"تم حذف {count} سجل")


@router.get("/logs/export")
def export_logs(db: Db, _: Admin) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["time", "level", "service", "worker", "job", "stage", "code", "message"])
    for row in db.execute(select(SystemLog).order_by(SystemLog.created_at.desc())).scalars():
        writer.writerow(
            [row.created_at, row.level, row.service, row.worker_name, row.job_id, row.stage, row.error_code, row.message]
        )
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=system-logs.csv"},
    )


@router.get("/settings")
def get_settings_endpoint(db: Db, _: Admin) -> dict[str, Any]:
    return {
        "values": get_all_settings(db),
        "fixed": {
            "audio_retention_hours": settings.audio_retention_hours,
            "worker_count": 5,
        },
        "secrets": {
            "deepgram_keys_configured": sum(bool(value) for value in [settings.deepgram_api_key_worker_1, settings.deepgram_api_key_worker_2, settings.deepgram_api_key_worker_3, settings.deepgram_api_key_worker_4, settings.deepgram_api_key_worker_5]),
            "cookies_configured": settings.cookies_path.exists(),
        },
    }


@router.put("/settings")
def put_settings(payload: SettingsPayload, db: Db, admin: CsrfAdmin) -> dict[str, Any]:
    try:
        values = update_settings(db, payload.values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, action="update_settings", actor=admin, details={"keys": list(payload.values)})
    return {"values": values}


@router.get("/youtube/cookies", response_model=CookieStatus)
def get_cookie_status(db: Db, _: Admin) -> dict[str, Any]:
    raw = cookie_status()
    if isinstance(raw.get("modified_at"), (int, float)):
        raw["modified_at"] = datetime.fromtimestamp(raw["modified_at"], UTC)
    test = db.get(AppSetting, "cookies_last_test")
    raw["last_test"] = test.value if test else None
    return raw


@router.post("/youtube/cookies", response_model=CookieStatus)
async def upload_cookies(
    request: Request,
    db: Db,
    admin: CsrfAdmin,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        result = save_cookies(content)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(
        db,
        action="upload_cookies",
        actor=admin,
        target_type="cookies",
        details={"size": len(content), "filename": file.filename},
        ip_address=get_client_ip(request),
    )
    if isinstance(result.get("modified_at"), (int, float)):
        result["modified_at"] = datetime.fromtimestamp(result["modified_at"], UTC)
    return result


@router.post("/youtube/cookies/test")
def test_cookies(db: Db, admin: CsrfAdmin) -> dict[str, Any]:
    if not settings.cookies_path.exists():
        raise HTTPException(404, "لا يوجد ملف Cookies")
    app_settings = get_all_settings(db)
    try:
        info = extract_info(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            flat_playlist=False,
            timeout=int(app_settings["metadata_timeout_seconds"]),
            use_cookies=True,
        )
        result = {"success": True, "tested_at": utcnow().isoformat(), "video_title": info.get("title")}
    except Exception as exc:
        result = {"success": False, "tested_at": utcnow().isoformat(), "error": str(exc)}
    row = db.get(AppSetting, "cookies_last_test")
    if row is None:
        row = AppSetting(key="cookies_last_test", value=result, category="youtube")
        db.add(row)
    else:
        row.value = result
    db.commit()
    audit(db, action="test_cookies", actor=admin, details={"success": result["success"]})
    return result


@router.post("/youtube/retry-waiting", response_model=MessageResponse)
def retry_cookie_jobs(db: Db, admin: CsrfAdmin) -> MessageResponse:
    jobs = list(
        db.execute(select(Job).where(Job.status == JobStatus.WAITING_FOR_COOKIES.value)).scalars()
    )
    for job in jobs:
        reset_job_for_retry(db, job)
        process_job.delay(job_id=job.id)
    batches = list(
        db.execute(select(Batch).where(Batch.status == JobStatus.WAITING_FOR_COOKIES.value)).scalars()
    )
    for batch in batches:
        batch.status = JobStatus.QUEUED.value
        db.commit()
        expand_source.delay(batch_id=batch.id)
    audit(db, action="retry_cookie_waiting", actor=admin, details={"jobs": len(jobs), "batches": len(batches)})
    return MessageResponse(message=f"أعيدت {len(jobs)} مهمة و{len(batches)} قائمة إلى الطابور")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Db, _: Admin) -> DashboardOut:
    counts = dict(db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    workers = dict(
        db.execute(select(WorkerState.status, func.count(WorkerState.name)).group_by(WorkerState.status)).all()
    )
    usage = shutil.disk_usage(settings.exports_root)
    recent_jobs = list(db.execute(select(Job).order_by(Job.created_at.desc()).limit(8)).scalars())
    recent_errors = list(
        db.execute(
            select(SystemLog)
            .where(SystemLog.level.in_([LogLevel.ERROR.value, LogLevel.CRITICAL.value]))
            .order_by(SystemLog.created_at.desc())
            .limit(8)
        ).scalars()
    )
    return DashboardOut(
        counts={str(k): int(v) for k, v in counts.items()},
        workers={str(k): int(v) for k, v in workers.items()},
        disk={"total": usage.total, "used": usage.used, "free": usage.free, "percent": round(usage.used / usage.total * 100, 1)},
        recent_jobs=recent_jobs,
        recent_errors=recent_errors,
    )


@router.get("/events/stream")
async def events_stream(_: Admin) -> StreamingResponse:
    async def event_generator():
        while True:
            yield f"event: refresh\ndata: {utcnow().isoformat()}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/health")
def health(db: Db) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        db.execute(select(func.now()))
        checks["database"] = "ok"
    except Exception as exc:
        raise HTTPException(503, f"database unavailable: {type(exc).__name__}") from exc
    try:
        Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception as exc:
        raise HTTPException(503, f"redis unavailable: {type(exc).__name__}") from exc
    for name, root in {
        "audio_storage": settings.audio_root,
        "exports_storage": settings.exports_root,
        "youtube_storage": settings.youtube_config_root,
    }.items():
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            checks[name] = "ok"
        except OSError as exc:
            raise HTTPException(503, f"{name} unavailable: {type(exc).__name__}") from exc
    return {"status": "healthy", "version": settings.app_version, "checks": checks}

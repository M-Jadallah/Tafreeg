from __future__ import annotations

import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask

from app.core.db import get_db
from app.core.models import ExportArtifact, Job
from app.core.security import require_csrf
from app.services.export_service import ensure_exports, safe_filename
from app.services.log_service import audit

router = APIRouter(prefix="/api")
Db = Annotated[Session, Depends(get_db)]
CsrfAdmin = Annotated[str, Depends(require_csrf)]
ExportFormat = Literal["docx", "txt", "json"]


class BulkExportRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)
    formats: list[ExportFormat] = Field(min_length=1, max_length=3)

    @field_validator("job_ids")
    @classmethod
    def unique_job_ids(cls, value: list[str]) -> list[str]:
        unique = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not unique:
            raise ValueError("يجب تحديد تفريغ واحد على الأقل")
        return unique

    @field_validator("formats")
    @classmethod
    def unique_formats(cls, value: list[ExportFormat]) -> list[ExportFormat]:
        return list(dict.fromkeys(value))


def _delete_temp_archive(path: str) -> None:
    """Delete the temporary archive after Starlette finishes sending it."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        # Cleanup must never turn a successful download into a failed response.
        pass


def _validate_zip(path: Path) -> None:
    """Fail before sending if the generated ZIP is empty or structurally invalid."""
    if not path.exists() or path.stat().st_size < 22:
        raise RuntimeError("Generated ZIP archive is empty or incomplete")

    if not zipfile.is_zipfile(path):
        raise RuntimeError("Generated file is not a valid ZIP archive")

    with zipfile.ZipFile(path, mode="r") as archive:
        broken_member = archive.testzip()
        if broken_member is not None:
            raise RuntimeError(f"Corrupted ZIP member: {broken_member}")


@router.post("/jobs/bulk-export", response_class=FileResponse)
def bulk_export_jobs(
    payload: BulkExportRequest,
    db: Db,
    admin: CsrfAdmin,
) -> FileResponse:
    jobs = list(
        db.execute(
            select(Job)
            .where(Job.id.in_(payload.job_ids))
            .options(selectinload(Job.transcript), selectinload(Job.exports))
        ).scalars()
    )

    jobs_by_id = {job.id: job for job in jobs}
    ordered_jobs = [jobs_by_id[job_id] for job_id in payload.job_ids if job_id in jobs_by_id]
    exportable_jobs = [job for job in ordered_jobs if job.transcript is not None]

    if not exportable_jobs:
        raise HTTPException(status_code=422, detail="لا توجد تفريغات مكتملة ضمن العناصر المحددة")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix="tafreeg-bulk-export-",
        suffix=".zip",
    )
    os.close(file_descriptor)
    archive_path = Path(temporary_name)
    exported_files = 0

    try:
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as zip_file:
            for index, job in enumerate(exportable_jobs, start=1):
                artifacts = ensure_exports(db, job)
                artifacts_by_format: dict[str, ExportArtifact] = {
                    artifact.format: artifact for artifact in artifacts
                }
                title = safe_filename(job.title or job.youtube_video_id or job.id, job.id)
                folder = f"{index:03d} - {title}"

                for format_name in payload.formats:
                    artifact = artifacts_by_format.get(format_name)
                    if artifact is None:
                        continue

                    source_path = Path(artifact.file_path)
                    if not source_path.is_file() or source_path.stat().st_size == 0:
                        continue

                    zip_file.write(source_path, arcname=f"{folder}/{source_path.name}")
                    exported_files += 1

        if exported_files == 0:
            raise HTTPException(status_code=404, detail="لم يتم العثور على ملفات تصدير صالحة")

        # The ZIP is closed at this point, so its central directory has been written.
        _validate_zip(archive_path)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        download_filename = f"tafreeg-exports-{timestamp}.zip"

        audit(
            db,
            action="bulk_export_jobs",
            actor=admin,
            details={
                "jobs_count": len(exportable_jobs),
                "files_count": exported_files,
                "formats": list(payload.formats),
                "archive_bytes": archive_path.stat().st_size,
            },
        )

        # FileResponse sets Content-Length and streams a fully closed file.
        return FileResponse(
            path=archive_path,
            media_type="application/zip",
            filename=download_filename,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
            background=BackgroundTask(_delete_temp_archive, str(archive_path)),
        )
    except HTTPException:
        _delete_temp_archive(str(archive_path))
        raise
    except Exception as exc:
        _delete_temp_archive(str(archive_path))
        raise HTTPException(status_code=500, detail="تعذر إنشاء ملف ZIP صالح") from exc

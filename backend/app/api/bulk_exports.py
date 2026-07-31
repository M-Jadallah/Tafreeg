from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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


def _stream_archive(archive: tempfile.SpooledTemporaryFile[bytes]) -> Iterator[bytes]:
    try:
        while chunk := archive.read(1024 * 1024):
            yield chunk
    finally:
        archive.close()


@router.post("/jobs/bulk-export")
def bulk_export_jobs(
    payload: BulkExportRequest,
    db: Db,
    admin: CsrfAdmin,
) -> StreamingResponse:
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

    archive = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    exported_files = 0

    try:
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
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

                    path = Path(artifact.file_path)
                    if not path.exists() or path.stat().st_size == 0:
                        continue

                    zip_file.write(path, arcname=f"{folder}/{path.name}")
                    exported_files += 1

        if exported_files == 0:
            archive.close()
            raise HTTPException(status_code=404, detail="لم يتم العثور على ملفات تصدير صالحة")

        archive.seek(0)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"tafreeg-exports-{timestamp}.zip"

        audit(
            db,
            action="bulk_export_jobs",
            actor=admin,
            details={
                "jobs_count": len(exportable_jobs),
                "files_count": exported_files,
                "formats": list(payload.formats),
            },
        )

        return StreamingResponse(
            _stream_archive(archive),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception:
        if not archive.closed:
            archive.close()
        raise

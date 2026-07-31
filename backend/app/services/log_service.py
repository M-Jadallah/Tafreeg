from __future__ import annotations

import json
import logging
import re
import traceback
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import LogLevel
from app.core.models import AuditEvent, SystemLog

logger = logging.getLogger("transcriber")
settings = get_settings()
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*(?:token|bearer)\s+)[^\s]+"),
    re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._-]+"),
    re.compile(r"(?i)(password[\"'=:\s]+)[^\s,}\"]+"),
]


def redact(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    secrets_to_hide = (
        settings.deepgram_api_key,
        settings.deepgram_api_key_worker_1,
        settings.deepgram_api_key_worker_2,
        settings.deepgram_api_key_worker_3,
        settings.deepgram_api_key_worker_4,
        settings.deepgram_api_key_worker_5,
        settings.admin_password,
        settings.session_secret,
    )
    for secret in secrets_to_hide:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted[:100_000]


def write_log(
    db: Session,
    *,
    level: str = LogLevel.INFO.value,
    service: str = "api",
    message: str,
    worker_name: str | None = None,
    job_id: str | None = None,
    batch_id: str | None = None,
    stage: str | None = None,
    error_code: str | None = None,
    technical_details: str | None = None,
    retryable: bool = False,
    trace_id: str | None = None,
) -> str:
    trace_id = trace_id or str(uuid.uuid4())
    row = SystemLog(
        level=level,
        service=service,
        worker_name=worker_name,
        job_id=job_id,
        batch_id=batch_id,
        stage=stage,
        error_code=error_code,
        message=redact(message) or "",
        technical_details=redact(technical_details),
        retryable=retryable,
        trace_id=trace_id,
    )
    db.add(row)
    db.commit()
    console_payload = {
        "level": level,
        "service": service,
        "message": row.message,
        "worker": worker_name,
        "job_id": job_id,
        "stage": stage,
        "error_code": error_code,
        "trace_id": trace_id,
    }
    getattr(logger, "error" if level in {"error", "critical"} else "info")(
        json.dumps(console_payload, ensure_ascii=False)
    )
    return trace_id


def write_exception(db: Session, exc: BaseException, **kwargs: Any) -> str:
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return write_log(db, level=LogLevel.ERROR.value, technical_details=details, **kwargs)


def audit(
    db: Session,
    *,
    action: str,
    actor: str = "admin",
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
        )
    )
    db.commit()

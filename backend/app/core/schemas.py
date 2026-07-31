from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class LoginResponse(BaseModel):
    authenticated: bool = True
    username: str


class CreateBatchRequest(BaseModel):
    url: HttpUrl
    language: str = Field(default="ar", max_length=32)
    model: Literal[
        "whisper",
        "whisper-tiny",
        "whisper-base",
        "whisper-small",
        "whisper-medium",
        "whisper-large",
    ] = "whisper-large"
    paragraphs: bool = True
    utterances: bool = True
    punctuate: bool = True
    smart_format: bool = True


class BatchOut(BaseModel):
    id: str
    source_type: str
    source_url: str
    title: str | None
    status: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    created_at: datetime

    model_config = {"from_attributes": True}


class JobSummaryOut(BaseModel):
    id: str
    batch_id: str
    youtube_video_id: str | None
    source_url: str
    title: str | None
    channel: str | None
    thumbnail_url: str | None
    duration_seconds: float | None
    playlist_index: int | None
    status: str
    current_stage: str
    progress: float
    worker_name: str | None
    retry_count: int
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class TranscriptOut(BaseModel):
    id: str
    provider: str
    model: str
    language: str
    full_text: str
    paragraphs_json: Any | None
    utterances_json: Any | None
    words_json: Any | None
    request_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobEventOut(BaseModel):
    id: str
    event_type: str
    previous_status: str | None
    new_status: str | None
    message: str | None
    event_metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class JobAttemptOut(BaseModel):
    id: str
    attempt_number: int
    stage: str
    worker_name: str | None
    status: str
    error_code: str | None
    error_details: str | None
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class ExportOut(BaseModel):
    format: str
    file_size: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobDetailOut(JobSummaryOut):
    transcript: TranscriptOut | None = None
    events: list[JobEventOut] = Field(default_factory=list)
    attempts: list[JobAttemptOut] = Field(default_factory=list)
    exports: list[ExportOut] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    language: str
    model: str


class PaginatedJobs(BaseModel):
    items: list[JobSummaryOut]
    total: int
    page: int
    page_size: int


class WorkerOut(BaseModel):
    name: str
    status: str
    current_job_id: str | None
    current_stage: str | None
    last_heartbeat_at: datetime | None
    last_error: str | None
    successful_jobs: int
    failed_jobs: int
    started_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class LogOut(BaseModel):
    id: str
    level: str
    service: str
    worker_name: str | None
    job_id: str | None
    batch_id: str | None
    stage: str | None
    error_code: str | None
    message: str
    technical_details: str | None
    trace_id: str | None
    retryable: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedLogs(BaseModel):
    items: list[LogOut]
    total: int
    page: int
    page_size: int


class SettingsPayload(BaseModel):
    values: dict[str, Any]


class CookieStatus(BaseModel):
    exists: bool
    size: int | None = None
    modified_at: datetime | None = None
    valid_format: bool = False
    line_count: int | None = None
    expired_count: int | None = None
    session_count: int | None = None
    last_test: dict[str, Any] | None = None


class DashboardOut(BaseModel):
    counts: dict[str, int]
    workers: dict[str, int]
    disk: dict[str, Any]
    recent_jobs: list[JobSummaryOut]
    recent_errors: list[LogOut]


class BulkDeleteRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=500)


class MessageResponse(BaseModel):
    message: str

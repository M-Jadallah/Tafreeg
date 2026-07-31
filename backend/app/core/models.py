from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import (
    AttemptStatus,
    BatchType,
    ChunkStatus,
    JobStatus,
    LogLevel,
    WorkerStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_type: Mapped[str] = mapped_column(String(20), default=BatchType.UNKNOWN.value)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    youtube_playlist_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.CREATED.value, index=True)
    language: Mapped[str] = mapped_column(String(32), default="ar")
    model: Mapped[str] = mapped_column(String(64), default="whisper-large")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("batch_id", "youtube_video_id", name="uq_batch_video"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(128), index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    playlist_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.CREATED.value, index=True)
    current_stage: Mapped[str] = mapped_column(String(40), default=JobStatus.CREATED.value)
    progress: Mapped[float] = mapped_column(Float, default=0)
    worker_name: Mapped[str | None] = mapped_column(String(100), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    stage_retry_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    last_error_code: Mapped[str | None] = mapped_column(String(100), index=True)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lease_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(32), default="ar")
    model: Mapped[str] = mapped_column(String(64), default="whisper-large")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="jobs")
    attempts: Mapped[list["JobAttempt"]] = relationship(cascade="all, delete-orphan")
    events: Mapped[list["JobEvent"]] = relationship(cascade="all, delete-orphan")
    audio_artifacts: Mapped[list["AudioArtifact"]] = relationship(cascade="all, delete-orphan")
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    exports: Mapped[list["ExportArtifact"]] = relationship(cascade="all, delete-orphan")
    chunks: Mapped[list["TranscriptChunk"]] = relationship(cascade="all, delete-orphan")


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(40), index=True)
    worker_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default=AttemptStatus.RUNNING.value)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_details: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AudioArtifact(Base):
    __tablename__ = "audio_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="main")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="audio/mpeg")
    bitrate: Mapped[str | None] = mapped_column(String(20))
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="deepgram")
    model: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(32))
    full_text: Mapped[str] = mapped_column(Text, default="")
    paragraphs_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    utterances_json: Mapped[list[Any] | None] = mapped_column(JSON)
    words_json: Mapped[list[Any] | None] = mapped_column(JSON)
    raw_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="transcript")


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"
    __table_args__ = (UniqueConstraint("job_id", "chunk_index", name="uq_job_chunk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    offset_seconds: Mapped[float] = mapped_column(Float, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    file_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default=ChunkStatus.PENDING.value)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    raw_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"
    __table_args__ = (UniqueConstraint("job_id", "format", name="uq_job_export_format"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    format: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerState(Base):
    __tablename__ = "worker_states"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default=WorkerStatus.OFFLINE.value)
    current_job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    current_stage: Mapped[str | None] = mapped_column(String(40))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    successful_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"
    __table_args__ = (Index("ix_logs_created_level", "created_at", "level"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    level: Mapped[str] = mapped_column(String(20), default=LogLevel.INFO.value, index=True)
    service: Mapped[str] = mapped_column(String(100), index=True)
    worker_name: Mapped[str | None] = mapped_column(String(100), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    stage: Mapped[str | None] = mapped_column(String(40), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    technical_details: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(100), index=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(50), default="general")
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    action: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="admin")
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

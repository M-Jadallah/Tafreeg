from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, selectinload

from app.core.db import Base
from app.core.models import Batch, Job, JobEvent, Transcript
from app.services.deepgram_service import classify_deepgram_error, extract_transcript_payload
from app.services.errors import WorkflowError
from app.services.export_service import ensure_exports, safe_filename
from app.services.job_service import reset_job_for_retry
from app.services.settings_service import validate_setting
from app.services.youtube_service import (
    classify_ytdlp_error,
    detect_source_type,
    parse_download_progress,
    validate_youtube_url,
)


def make_session(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_youtube_url_and_playlist_detection():
    assert validate_youtube_url("https://youtu.be/abc123") == "https://youtu.be/abc123"
    assert detect_source_type("https://www.youtube.com/watch?v=x&list=PL123") == "playlist"
    assert detect_source_type("https://www.youtube.com/watch?v=x") == "video"
    with pytest.raises(WorkflowError) as error:
        validate_youtube_url("http://127.0.0.1/private")
    assert error.value.code == "YT_INVALID_URL"


def test_provider_error_classification_and_progress():
    assert parse_download_progress("[download]  42.5% of 3.00MiB") == 42.5
    assert classify_ytdlp_error("Sign in to confirm you’re not a bot").requires_cookies
    assert classify_ytdlp_error("HTTP Error 429: Too Many Requests").retryable
    assert classify_deepgram_error(429, "rate limit").retryable
    assert classify_deepgram_error(401, "bad key").code == "DG_INVALID_API_KEY"
    assert not classify_deepgram_error(401, "bad key").retryable


def test_deepgram_timestamps_are_offset():
    payload = extract_transcript_payload(
        {
            "metadata": {"request_id": "request-1"},
            "results": {
                "channels": [{"alternatives": [{"transcript": "مرحبا", "words": [{"word": "مرحبا", "start": 1.0, "end": 1.5}]}]}],
                "utterances": [{"transcript": "مرحبا", "start": 1.0, "end": 1.5}],
            },
        },
        offset_seconds=600,
    )
    assert payload["text"] == "مرحبا"
    assert payload["words"][0]["start"] == 601.0
    assert payload["utterances"][0]["end"] == 601.5
    assert payload["request_id"] == "request-1"


def test_settings_validation():
    assert validate_setting("audio_bitrate", "64k") == "64k"
    assert validate_setting("download_max_retries", "5") == 5
    with pytest.raises(ValueError):
        validate_setting("audio_bitrate", "256k")
    with pytest.raises(ValueError):
        validate_setting("disk_warning_percent", 10)


def test_manual_retry_event_preserves_previous_status(tmp_path: Path):
    db = make_session(tmp_path)
    batch = Batch(source_url="https://youtu.be/test", source_type="video")
    db.add(batch)
    db.flush()
    job = Job(
        batch_id=batch.id,
        source_url=batch.source_url,
        youtube_video_id="test",
        status="FAILED",
        current_stage="FAILED",
    )
    db.add(job)
    db.commit()
    reset_job_for_retry(db, job)
    event = db.execute(select(JobEvent).where(JobEvent.job_id == job.id)).scalar_one()
    assert event.previous_status == "FAILED"
    assert event.new_status == "queued"
    db.close()


def test_exports_are_persistent_and_arabic_rtl(tmp_path: Path):
    db = make_session(tmp_path)
    batch = Batch(source_url="https://youtu.be/test", source_type="video")
    db.add(batch)
    db.flush()
    job = Job(
        batch_id=batch.id,
        source_url=batch.source_url,
        youtube_video_id="test",
        title="عنوان عربي / آمن؟",
        channel="قناة الاختبار",
        status="COMPLETED",
        current_stage="COMPLETED",
        language="ar",
        model="whisper-large",
    )
    db.add(job)
    db.flush()
    db.add(
        Transcript(
            job_id=job.id,
            model="whisper-large",
            language="ar",
            full_text="هذا نص عربي.\nوهذه فقرة ثانية.",
            paragraphs_json={},
            utterances_json=[],
            words_json=[],
            raw_response_json={"metadata": {"request_id": "r1"}},
            request_id="r1",
        )
    )
    db.commit()
    job = db.execute(
        select(Job)
        .where(Job.id == job.id)
        .options(selectinload(Job.transcript), selectinload(Job.exports))
    ).scalar_one()
    artifacts = ensure_exports(db, job)
    paths = {artifact.format: Path(artifact.file_path) for artifact in artifacts}
    assert set(paths) == {"docx", "txt", "json"}
    assert all(path.exists() and path.stat().st_size > 0 for path in paths.values())
    with zipfile.ZipFile(paths["docx"]) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        assert "هذا نص عربي" in xml
        assert "w:bidi" in xml
    assert "هذا نص عربي" in paths["txt"].read_text("utf-8")
    assert json.loads(paths["json"].read_text("utf-8"))["transcription"]["language"] == "ar"
    assert "/" not in safe_filename(job.title or "", job.id)
    db.close()

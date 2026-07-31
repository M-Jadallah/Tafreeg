from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.models import AudioArtifact, Job, TranscriptChunk, utcnow
from app.services.errors import WorkflowError

settings = get_settings()


def run_process(command: list[str], timeout: int, error_code: str, user_message: str) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(error_code, user_message, str(exc), True) from exc
    if result.returncode != 0:
        raise WorkflowError(error_code, user_message, result.stderr or result.stdout, True)
    return result.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_audio(path: Path, timeout: int = 60) -> dict[str, Any]:
    output = run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=codec_type,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        timeout,
        "AUDIO_PROBE_FAILED",
        "تعذر التحقق من الملف الصوتي",
    )
    try:
        data = json.loads(output)
        audio_stream = next(
            stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"
        )
        fmt = data.get("format", {})
        return {
            "duration": float(fmt.get("duration", 0)),
            "size": int(fmt.get("size", path.stat().st_size)),
            "bit_rate": int(fmt.get("bit_rate", 0) or 0),
            "sample_rate": int(audio_stream.get("sample_rate", 0) or 0),
            "channels": int(audio_stream.get("channels", 0) or 0),
        }
    except (ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        raise WorkflowError(
            "AUDIO_INVALID_OUTPUT",
            "الملف الصوتي الناتج غير صالح",
            output,
            True,
        ) from exc


def transcode_audio(
    source: Path,
    destination: Path,
    *,
    bitrate: str,
    sample_rate: int,
    channels: int,
    timeout: int,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.mp3")
    temporary.unlink(missing_ok=True)
    run_process(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-b:a",
            bitrate,
            "-codec:a",
            "libmp3lame",
            str(temporary),
        ],
        timeout,
        "AUDIO_TRANSCODE_FAILED",
        "فشل تحويل الصوت إلى MP3",
    )
    metadata = probe_audio(temporary)
    if metadata["duration"] <= 0 or metadata["size"] <= 0:
        temporary.unlink(missing_ok=True)
        raise WorkflowError("AUDIO_INVALID_OUTPUT", "الملف الصوتي الناتج فارغ", retryable=True)
    temporary.replace(destination)
    metadata["checksum"] = sha256_file(destination)
    return metadata


def create_audio_artifact(job: Job, path: Path, metadata: dict[str, Any]) -> AudioArtifact:
    return AudioArtifact(
        job_id=job.id,
        kind="main",
        file_path=str(path),
        mime_type="audio/mpeg",
        bitrate=settings.audio_bitrate,
        sample_rate=metadata.get("sample_rate"),
        channels=metadata.get("channels"),
        duration=metadata.get("duration"),
        file_size=metadata.get("size"),
        checksum=metadata.get("checksum"),
        delete_after=utcnow() + timedelta(hours=settings.audio_retention_hours),
    )


def split_audio(
    job: Job,
    source: Path,
    *,
    duration: float,
    chunk_seconds: int,
    timeout: int,
) -> list[TranscriptChunk]:
    job_dir = source.parent / "chunks"
    job_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, math.ceil(duration / chunk_seconds))
    chunks: list[TranscriptChunk] = []
    for index in range(count):
        offset = index * chunk_seconds
        chunk_duration = min(chunk_seconds, max(0, duration - offset))
        path = job_dir / f"chunk-{index:04d}.mp3"
        if not path.exists() or path.stat().st_size == 0:
            temporary = path.with_suffix(".tmp.mp3")
            run_process(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(offset),
                    "-t",
                    str(chunk_duration),
                    "-i",
                    str(source),
                    "-acodec",
                    "copy",
                    str(temporary),
                ],
                timeout,
                "AUDIO_CHUNK_FAILED",
                "فشل تقسيم الملف الصوتي الطويل",
            )
            temporary.replace(path)
        chunks.append(
            TranscriptChunk(
                job_id=job.id,
                chunk_index=index,
                offset_seconds=float(offset),
                duration_seconds=float(chunk_duration),
                file_path=str(path),
                status="ready",
            )
        )
    return chunks


def ensure_chunk_audio(source: Path, chunk: TranscriptChunk, *, timeout: int) -> Path:
    """Recreate a missing unfinished chunk after the 24-hour audio cleanup."""
    path = Path(chunk.file_path)
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.mp3")
    temporary.unlink(missing_ok=True)
    run_process(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(chunk.offset_seconds),
            "-t",
            str(chunk.duration_seconds or 0),
            "-i",
            str(source),
            "-acodec",
            "copy",
            str(temporary),
        ],
        timeout,
        "AUDIO_CHUNK_FAILED",
        "فشل إعادة إنشاء جزء صوتي مفقود",
    )
    temporary.replace(path)
    return path

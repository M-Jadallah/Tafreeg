from __future__ import annotations

import json
import os
import re
import subprocess
import selectors
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings
from app.services.errors import WorkflowError

settings = get_settings()
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise WorkflowError("YT_INVALID_URL", "الرابط ليس رابط YouTube صالحًا")
    return url.strip()


def detect_source_type(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "list" in query or "/playlist" in parsed.path:
        return "playlist"
    return "video"


def cookie_status() -> dict[str, Any]:
    path = settings.cookies_path
    if not path.exists():
        return {"exists": False, "valid_format": False}
    stat = path.stat()
    try:
        text = path.read_text("utf-8", errors="replace")
        valid = text.startswith("# Netscape HTTP Cookie File") or text.startswith(
            "# HTTP Cookie File"
        )
        cookie_lines = [
            line for line in text.splitlines()
            if line and (not line.startswith("#") or line.startswith("#HttpOnly_"))
        ]
        line_count = len(cookie_lines)
        now_epoch = int(time.time())
        expired_count = 0
        session_count = 0
        for line in cookie_lines:
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            try:
                expires = int(parts[4])
            except ValueError:
                continue
            if expires <= 0:
                session_count += 1
            elif expires <= now_epoch:
                expired_count += 1
    except OSError:
        valid = False
        line_count = 0
        expired_count = 0
        session_count = 0
    return {
        "exists": True,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "valid_format": valid,
        "line_count": line_count,
        "expired_count": expired_count,
        "session_count": session_count,
    }


def save_cookies(content: bytes) -> dict[str, Any]:
    if len(content) > settings.max_upload_bytes:
        raise WorkflowError("YT_COOKIES_TOO_LARGE", "ملف Cookies أكبر من الحد المسموح")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkflowError("YT_COOKIES_ENCODING", "ملف Cookies يجب أن يكون UTF-8") from exc
    if not (
        text.startswith("# Netscape HTTP Cookie File")
        or text.startswith("# HTTP Cookie File")
    ):
        raise WorkflowError(
            "YT_COOKIES_FORMAT",
            "ملف Cookies ليس بصيغة Netscape cookies.txt الصحيحة",
        )
    settings.youtube_config_root.mkdir(parents=True, exist_ok=True)
    temporary = settings.cookies_path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(settings.cookies_path)
    os.chmod(settings.cookies_path, 0o600)
    return cookie_status()


def classify_ytdlp_error(output: str) -> WorkflowError:
    lowered = output.lower()
    cookie_markers = (
        "sign in to confirm",
        "sign in to verify",
        "confirm you’re not a bot",
        "confirm you're not a bot",
        "login required",
        "cookies",
        "age-restricted",
        "age restricted",
    )
    if any(marker in lowered for marker in cookie_markers):
        return WorkflowError(
            "YT_COOKIES_REQUIRED",
            "يتطلب الفيديو Cookies صالحة من YouTube",
            output,
            retryable=False,
            requires_cookies=True,
        )
    if "private video" in lowered:
        return WorkflowError("YT_PRIVATE_VIDEO", "الفيديو خاص وغير متاح", output)
    if "video unavailable" in lowered or "this video is unavailable" in lowered:
        return WorkflowError("YT_VIDEO_UNAVAILABLE", "الفيديو غير متاح أو محذوف", output)
    if "unsupported url" in lowered:
        return WorkflowError("YT_UNSUPPORTED_URL", "رابط YouTube غير مدعوم", output)
    if "requested format is not available" in lowered:
        return WorkflowError("YT_FORMAT_UNAVAILABLE", "لم يتم العثور على مسار صوتي مناسب", output, True)
    if "http error 429" in lowered or "too many requests" in lowered:
        return WorkflowError("YT_RATE_LIMITED", "فرض YouTube حدًا مؤقتًا على الطلبات", output, True)
    if "timed out" in lowered or "timeout" in lowered:
        return WorkflowError("YT_DOWNLOAD_TIMEOUT", "انتهت مهلة الاتصال بـYouTube", output, True)
    if "unable to download" in lowered or "network" in lowered or "connection" in lowered:
        return WorkflowError("YT_NETWORK_ERROR", "تعذر الاتصال بـYouTube مؤقتًا", output, True)
    return WorkflowError("YT_DOWNLOAD_FAILED", "فشل تنفيذ yt-dlp", output, True)


def _base_command() -> list[str]:
    return [
        "yt-dlp",
        "--no-warnings",
        "--newline",
        "--js-runtimes",
        "node",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--retry-sleep",
        "http:linear=1:5:2",
        "--socket-timeout",
        "30",
    ]


def run_command(
    command: list[str],
    *,
    timeout: int,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            if time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=10)
                raise WorkflowError(
                    "YT_DOWNLOAD_TIMEOUT",
                    "انتهت مهلة تنفيذ yt-dlp",
                    "".join(lines),
                    True,
                )
            events = selector.select(timeout=1.0)
            for key, _ in events:
                line = key.fileobj.readline()
                if line:
                    lines.append(line)
                    if progress_callback:
                        try:
                            progress_callback(line.strip())
                        except BaseException:
                            process.kill()
                            process.wait(timeout=10)
                            raise
            if process.poll() is not None:
                remainder = process.stdout.read()
                if remainder:
                    lines.append(remainder)
                break
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    output = "".join(lines)
    if process.returncode != 0:
        raise classify_ytdlp_error(output)
    return output


def extract_info(url: str, *, flat_playlist: bool, timeout: int, use_cookies: bool = False) -> dict:
    validate_youtube_url(url)
    command = _base_command() + ["--dump-single-json", "--skip-download"]
    if flat_playlist:
        command += ["--flat-playlist", "--yes-playlist"]
    else:
        command += ["--no-playlist"]
    if use_cookies and settings.cookies_path.exists():
        command += ["--cookies", str(settings.cookies_path)]
    command.append(url)
    output = run_command(command, timeout=timeout)
    try:
        return json.loads(output.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise WorkflowError("YT_METADATA_INVALID", "تعذر قراءة معلومات YouTube", output, True) from exc


def extract_info_with_cookie_fallback(url: str, *, flat_playlist: bool, timeout: int) -> dict:
    try:
        return extract_info(url, flat_playlist=flat_playlist, timeout=timeout, use_cookies=False)
    except WorkflowError as exc:
        if exc.requires_cookies and settings.cookies_path.exists():
            return extract_info(url, flat_playlist=flat_playlist, timeout=timeout, use_cookies=True)
        raise


def parse_download_progress(line: str) -> float | None:
    match = re.search(r"\[download\]\s+([0-9.]+)%", line)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def download_audio_source(
    url: str,
    output_dir: Path,
    *,
    timeout: int,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "source.%(ext)s")

    def callback(line: str) -> None:
        progress = parse_download_progress(line)
        if progress is not None and progress_callback:
            progress_callback(progress)

    def execute(use_cookies: bool) -> None:
        command = _base_command() + [
            "--no-playlist",
            "--continue",
            "--part",
            "-f",
            "bestaudio/best",
            "-o",
            template,
        ]
        if use_cookies and settings.cookies_path.exists():
            command += ["--cookies", str(settings.cookies_path)]
        command.append(url)
        run_command(command, timeout=timeout, progress_callback=callback)

    try:
        execute(False)
    except WorkflowError as exc:
        if exc.requires_cookies and settings.cookies_path.exists():
            execute(True)
        else:
            raise
    candidates = [
        path
        for path in output_dir.glob("source.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise WorkflowError("YT_AUDIO_MISSING", "اكتمل التنزيل دون العثور على ملف الصوت", retryable=True)
    return max(candidates, key=lambda path: path.stat().st_size)

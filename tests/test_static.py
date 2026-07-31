from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_required_files_exist():
    required = [
        "docker-compose.yml",
        ".env.example",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "backend/app/main.py",
        "backend/app/workers/tasks.py",
        "frontend/src/App.tsx",
        "docs/COOLIFY_DEPLOYMENT.md",
    ]
    for item in required:
        assert (ROOT / item).exists(), item


def test_five_workers_are_independent_and_healthy():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    workers = [services[f"worker-{index}"] for index in range(1, 6)]
    assert len(workers) == 5
    for index, worker in enumerate(workers, start=1):
        command = " ".join(worker["command"])
        assert "--concurrency=1" in command
        assert worker["environment"]["WORKER_NAME"] == f"worker-{index}"
        assert "DEEPGRAM_API_KEY" in worker["environment"]
        assert "healthcheck" in worker


def test_scheduler_only_auto_deletes_temporary_audio():
    scheduler = (ROOT / "backend/app/scheduler.py").read_text()
    assert "AudioArtifact" in scheduler
    assert "audio_retention_hours" in scheduler
    assert "Transcript).delete" not in scheduler
    assert "ExportArtifact).delete" not in scheduler


def test_audio_defaults_and_formats():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "AUDIO_RETENTION_HOURS: 24" in compose
    assert "AUDIO_BITRATE: 64k" in compose
    exports = (ROOT / "backend/app/services/export_service.py").read_text()
    assert '"docx"' in exports and '"txt"' in exports and '"json"' in exports


def test_no_real_secrets_committed():
    import re

    # Error codes such as DG_RATE_LIMITED are legitimate source text. Scan only
    # for values that resemble actual provider secrets or populated env values.
    patterns = [
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(
            r"DEEPGRAM_API_KEY(?:_WORKER_\d+)?[ \t]*=[ \t]*[A-Za-z0-9_-]{24,}",
            re.IGNORECASE,
        ),
    ]
    for candidate in ROOT.rglob("*"):
        if not candidate.is_file() or ".git" in candidate.parts:
            continue
        if candidate.suffix in {".pyc", ".zip", ".whl"}:
            continue
        text = candidate.read_text("utf-8", errors="ignore")
        assert not any(pattern.search(text) for pattern in patterns), candidate


def test_saved_transcript_skips_audio_pipeline():
    tasks = (ROOT / "backend/app/workers/tasks.py").read_text()
    checkpoint = tasks.index("if job.transcript is not None")
    download_stage = tasks.index("download_audio_source(", checkpoint)
    assert checkpoint < download_stage
    assert "return _finalize_success(db, job, attempt)" in tasks[checkpoint:download_stage]

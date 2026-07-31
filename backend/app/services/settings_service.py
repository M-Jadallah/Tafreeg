from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import AppSetting

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "metadata_max_retries": {"value": 3, "category": "retry"},
    "download_max_retries": {"value": 5, "category": "retry"},
    "transcode_max_retries": {"value": 2, "category": "retry"},
    "deepgram_max_retries": {"value": 5, "category": "retry"},
    "export_max_retries": {"value": 2, "category": "retry"},
    "retry_initial_seconds": {"value": 30, "category": "retry"},
    "retry_multiplier": {"value": 2.0, "category": "retry"},
    "retry_max_seconds": {"value": 900, "category": "retry"},
    "retry_jitter_seconds": {"value": 15, "category": "retry"},
    "metadata_timeout_seconds": {"value": 180, "category": "timeouts"},
    "download_timeout_seconds": {"value": 7200, "category": "timeouts"},
    "ffmpeg_timeout_seconds": {"value": 7200, "category": "timeouts"},
    "deepgram_timeout_seconds": {"value": 1800, "category": "timeouts"},
    "default_language": {"value": "ar", "category": "deepgram"},
    "default_model": {"value": "whisper-large", "category": "deepgram"},
    "deepgram_punctuate": {"value": True, "category": "deepgram"},
    "deepgram_paragraphs": {"value": True, "category": "deepgram"},
    "deepgram_utterances": {"value": True, "category": "deepgram"},
    "deepgram_smart_format": {"value": True, "category": "deepgram"},
    "long_audio_threshold_seconds": {"value": 900, "category": "audio"},
    "chunk_duration_seconds": {"value": 600, "category": "audio"},
    "audio_bitrate": {"value": "64k", "category": "audio"},
    "audio_sample_rate": {"value": 16000, "category": "audio"},
    "audio_channels": {"value": 1, "category": "audio"},
    "page_size": {"value": 25, "category": "ui"},
    "disk_warning_percent": {"value": 70, "category": "system"},
    "disk_critical_percent": {"value": 85, "category": "system"},
}

VALIDATORS: dict[str, tuple[type, Any, Any]] = {
    "metadata_max_retries": (int, 0, 20),
    "download_max_retries": (int, 0, 20),
    "transcode_max_retries": (int, 0, 20),
    "deepgram_max_retries": (int, 0, 20),
    "export_max_retries": (int, 0, 20),
    "retry_initial_seconds": (int, 1, 3600),
    "retry_multiplier": (float, 1.0, 10.0),
    "retry_max_seconds": (int, 1, 86400),
    "retry_jitter_seconds": (int, 0, 3600),
    "metadata_timeout_seconds": (int, 10, 3600),
    "download_timeout_seconds": (int, 60, 86400),
    "ffmpeg_timeout_seconds": (int, 60, 86400),
    "deepgram_timeout_seconds": (int, 60, 86400),
    "long_audio_threshold_seconds": (int, 300, 86400),
    "chunk_duration_seconds": (int, 300, 7200),
    "audio_sample_rate": (int, 8000, 48000),
    "audio_channels": (int, 1, 2),
    "page_size": (int, 10, 100),
    "disk_warning_percent": (int, 50, 95),
    "disk_critical_percent": (int, 60, 99),
}

ALLOWED_MODELS = {
    "whisper-tiny",
    "whisper-base",
    "whisper-small",
    "whisper-medium",
    "whisper-large",
    "whisper",
}


def seed_defaults(db: Session) -> None:
    existing = {row.key for row in db.query(AppSetting.key).all()}
    for key, meta in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(AppSetting(key=key, value=meta["value"], category=meta["category"]))
    db.commit()


def get_all_settings(db: Session) -> dict[str, Any]:
    seed_defaults(db)
    values = deepcopy({key: meta["value"] for key, meta in DEFAULT_SETTINGS.items()})
    for row in db.query(AppSetting).all():
        if row.key in values:
            values[row.key] = row.value
    return values


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS[key]["value"]


def validate_setting(key: str, value: Any) -> Any:
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"إعداد غير معروف: {key}")
    if key == "default_model":
        if value not in ALLOWED_MODELS:
            raise ValueError("نموذج Deepgram غير مدعوم")
        return value
    if key == "audio_bitrate":
        if value not in {"32k", "48k", "64k", "96k"}:
            raise ValueError("قيمة bitrate غير مدعومة")
        return value
    expected = type(DEFAULT_SETTINGS[key]["value"])
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"القيمة {key} يجب أن تكون true أو false")
        return value
    if key in VALIDATORS:
        value_type, minimum, maximum = VALIDATORS[key]
        try:
            converted = value_type(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"قيمة غير صحيحة للإعداد {key}") from exc
        if not minimum <= converted <= maximum:
            raise ValueError(f"الإعداد {key} يجب أن يكون بين {minimum} و{maximum}")
        return converted
    if not isinstance(value, expected):
        raise ValueError(f"نوع قيمة غير صحيح للإعداد {key}")
    return value


def update_settings(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    merged = get_all_settings(db)
    validated: dict[str, Any] = {}
    for key, raw_value in values.items():
        validated[key] = validate_setting(key, raw_value)
    merged.update(validated)
    if int(merged["disk_critical_percent"]) <= int(merged["disk_warning_percent"]):
        raise ValueError("يجب أن يكون حد القرص الحرج أكبر من حد التحذير")
    for key, value in validated.items():
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(
                key=key,
                value=value,
                category=DEFAULT_SETTINGS[key]["category"],
            )
            db.add(row)
        else:
            row.value = value
    db.commit()
    return get_all_settings(db)

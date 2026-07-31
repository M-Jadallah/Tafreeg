from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.errors import WorkflowError

settings = get_settings()


def classify_deepgram_error(status_code: int, body: str) -> WorkflowError:
    if status_code == 401:
        return WorkflowError(
            "DG_INVALID_API_KEY",
            "مفتاح Deepgram الخاص بالعامل غير صالح أو لا يملك صلاحية",
            body,
            False,
        )
    if status_code == 402:
        return WorkflowError(
            "DG_INSUFFICIENT_CREDITS",
            "لا توجد أرصدة كافية في مشروع Deepgram",
            body,
            False,
        )
    if status_code == 403:
        return WorkflowError(
            "DG_MODEL_FORBIDDEN",
            "مشروع Deepgram لا يملك صلاحية استخدام النموذج المطلوب",
            body,
            False,
        )
    if status_code == 413:
        return WorkflowError(
            "DG_FILE_TOO_LARGE",
            "الملف الصوتي أكبر من الحد الذي يقبله Deepgram",
            body,
            False,
        )
    if status_code == 422:
        return WorkflowError(
            "DG_UPLOAD_INCOMPLETE",
            "لم يستطع Deepgram قراءة الملف كاملًا، وستعاد المحاولة",
            body,
            True,
        )
    if status_code == 429:
        return WorkflowError(
            "DG_RATE_LIMITED",
            "تم بلوغ حد الطلبات المتزامنة أو حد الاستخدام في Deepgram",
            body,
            True,
        )
    if status_code in {408, 499, 504}:
        return WorkflowError("DG_TIMEOUT", "انتهت مهلة Deepgram أو انقطع رفع الملف", body, True)
    if status_code >= 500:
        return WorkflowError("DG_SERVER_ERROR", "حدث خطأ مؤقت لدى Deepgram", body, True)
    return WorkflowError("DG_REQUEST_FAILED", "رفض Deepgram طلب التفريغ", body, False)


def transcribe_file(
    path: Path,
    *,
    api_key: str,
    model: str,
    language: str,
    options: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if not api_key:
        raise WorkflowError("DG_API_KEY_MISSING", "مفتاح Deepgram غير موجود لهذا العامل")
    params: dict[str, str] = {
        "model": model,
        "punctuate": str(bool(options.get("punctuate", True))).lower(),
        "paragraphs": str(bool(options.get("paragraphs", True))).lower(),
        "utterances": str(bool(options.get("utterances", True))).lower(),
        "smart_format": str(bool(options.get("smart_format", True))).lower(),
    }
    if language.strip().lower() in {"", "auto", "detect"}:
        params["detect_language"] = "true"
    else:
        params["language"] = language.strip().lower()
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "audio/mpeg"}
    timeout = httpx.Timeout(timeout_seconds, connect=30.0)
    try:
        with path.open("rb") as audio, httpx.Client(timeout=timeout) as client:
            response = client.post(
                settings.deepgram_base_url,
                params=params,
                headers=headers,
                content=audio,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise WorkflowError("DG_NETWORK_ERROR", "تعذر الاتصال بـDeepgram مؤقتًا", str(exc), True) from exc
    if response.status_code >= 400:
        raise classify_deepgram_error(response.status_code, response.text)
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise WorkflowError(
            "DG_RESPONSE_INVALID",
            "أعاد Deepgram استجابة غير صالحة",
            response.text,
            True,
        ) from exc
    if "results" not in data:
        raise WorkflowError(
            "DG_RESPONSE_EMPTY",
            "لم تتضمن استجابة Deepgram نتيجة تفريغ",
            json.dumps(data, ensure_ascii=False),
            True,
        )
    return data


def extract_transcript_payload(data: dict[str, Any], offset_seconds: float = 0) -> dict[str, Any]:
    results = data.get("results", {})
    channels = results.get("channels", [])
    alternatives = channels[0].get("alternatives", []) if channels else []
    alternative = alternatives[0] if alternatives else {}
    text = str(alternative.get("transcript", "")).strip()
    words = []
    for word in alternative.get("words", []) or []:
        item = dict(word)
        if isinstance(item.get("start"), (int, float)):
            item["start"] = float(item["start"]) + offset_seconds
        if isinstance(item.get("end"), (int, float)):
            item["end"] = float(item["end"]) + offset_seconds
        words.append(item)
    utterances = []
    for utterance in results.get("utterances", []) or []:
        item = dict(utterance)
        if isinstance(item.get("start"), (int, float)):
            item["start"] = float(item["start"]) + offset_seconds
        if isinstance(item.get("end"), (int, float)):
            item["end"] = float(item["end"]) + offset_seconds
        if item.get("words"):
            adjusted_words = []
            for word in item["words"]:
                adjusted = dict(word)
                if isinstance(adjusted.get("start"), (int, float)):
                    adjusted["start"] = float(adjusted["start"]) + offset_seconds
                if isinstance(adjusted.get("end"), (int, float)):
                    adjusted["end"] = float(adjusted["end"]) + offset_seconds
                adjusted_words.append(adjusted)
            item["words"] = adjusted_words
        utterances.append(item)
    paragraphs = alternative.get("paragraphs")
    metadata = data.get("metadata", {})
    return {
        "text": text,
        "words": words,
        "utterances": utterances,
        "paragraphs": paragraphs,
        "request_id": metadata.get("request_id"),
    }

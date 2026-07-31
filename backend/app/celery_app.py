from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "youtube_transcriber",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Register lifecycle signal handlers.
from app.workers import lifecycle as _lifecycle  # noqa: E402,F401

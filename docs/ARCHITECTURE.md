# المعمارية

```text
Browser → Gateway/Nginx → FastAPI
                         ├─ PostgreSQL
                         ├─ Redis/Celery
                         ├─ Shared audio volume
                         └─ Exports volume

Redis → worker-1..worker-5 → yt-dlp/FFmpeg → Deepgram Whisper
Scheduler → audio cleanup + stale lease recovery + worker offline detection
```

## الاستكمال

تتحقق المهمة عند كل إعادة تشغيل من وجود:

1. Metadata.
2. AudioArtifact صالح.
3. TranscriptChunk مكتمل للملفات الطويلة.
4. Transcript محفوظ.
5. ExportArtifact موجود.

وبذلك تعود إلى أول مرحلة ناقصة فقط.

## الاعتمادية

- `task_acks_late=true`
- `task_reject_on_worker_lost=true`
- `worker_prefetch_multiplier=1`
- `concurrency=1` لكل Worker
- PostgreSQL Lease لكل مهمة
- Heartbeat كل 15 ثانية
- استعادة Lease منتهية كل دقيقة

# مفرغ فيديوهات YouTube باستخدام Deepgram Whisper

تطبيق ويب عربي خاص بمدير واحد، يستقبل رابط فيديو YouTube أو Playlist، ينزل الصوت مؤقتًا، يحوله إلى MP3 أحادي القناة 16kHz/64kbps، ثم يرسله إلى Deepgram Whisper. يعمل بخمس حاويات Workers مستقلة، ويحفظ التفريغات وملفات Word وTXT وJSON بشكل دائم.

## المكونات

- React + TypeScript + Vite
- FastAPI + SQLAlchemy + Alembic
- Celery + Redis
- PostgreSQL
- yt-dlp + Node.js 22 + FFmpeg
- 5 Workers، كل Worker بمفتاح Deepgram مستقل
- Scheduler مستقل لتنظيف الصوت بعد 24 ساعة واستعادة المهام العالقة
- Nginx كبوابة موحدة

## تشغيل سريع محليًا

1. انسخ `.env.example` إلى `.env`.
2. عدّل جميع القيم المطلوبة، خصوصًا مفاتيح Deepgram الخمسة وبيانات المدير.
3. شغّل:

```bash
docker compose up --build -d
```

4. افتح المنفذ الذي توجهه إلى خدمة `gateway`، أو اربط Domain بالخدمة داخل Coolify.

## قواعد التخزين

- التفريغات وWord وTXT وJSON لا تُحذف تلقائيًا.
- الحذف النهائي يتم من الواجهة فقط وبعد التأكيد.
- ملفات الصوت المؤقتة تُحذف بعد 24 ساعة ما لم تكن مهمة نشطة تستخدمها.
- جميع البيانات الدائمة محفوظة في Docker Volumes.

## ملاحظة حدود Deepgram

التطبيق ينشئ خمسة Workers كما هو مطلوب. حدود التزامن في Deepgram تطبق على مستوى المشروع وليس على مستوى مفتاح API؛ لذلك لا تعني المفاتيح الخمسة مضاعفة حد المشروع. يدير التطبيق أي استجابة HTTP 429 بإعادة محاولة تلقائية مع تراجع زمني متزايد.

## الوثائق

- `docs/COOLIFY_DEPLOYMENT.md`
- `docs/ENVIRONMENT_VARIABLES.md`
- `docs/YOUTUBE_COOKIES.md`
- `docs/TROUBLESHOOTING.md`
- `docs/BACKUP_AND_RESTORE.md`
- `docs/ARCHITECTURE.md`
- `docs/SECURITY.md`
- `docs/VALIDATION_REPORT.md`

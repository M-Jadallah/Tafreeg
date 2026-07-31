# الأمان

- مستخدم واحد فقط، ولا توجد عملية تسجيل حسابات.
- Session JWT داخل Cookie من نوع HttpOnly وSameSite Strict.
- CSRF Double Submit لجميع العمليات المعدلة.
- Rate limit لمحاولات تسجيل الدخول باستخدام Redis.
- قبول نطاقات YouTube المعروفة فقط لمنع SSRF.
- تشغيل yt-dlp وFFmpeg دون Shell.
- عدم كشف Redis أو PostgreSQL أو Workers للإنترنت.
- إخفاء الأسرار وكلمات المرور وAuthorization من السجلات.
- ملف Cookies بصلاحيات `0600`.
- جميع عمليات الحذف تسجل كـAudit Events.

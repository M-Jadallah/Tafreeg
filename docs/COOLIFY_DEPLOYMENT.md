# النشر على Coolify

## 1. رفع المشروع

ارفع المجلد إلى GitHub/GitLab أو إلى مستودع Git خاص. أنشئ في Coolify موردًا جديدًا من نوع **Docker Compose** واختر المستودع، ثم اجعل مسار Compose هو:

```text
docker-compose.yml
```

## 2. المتغيرات البيئية

سيقرأ Coolify المتغيرات المذكورة داخل Compose. كل متغير بصيغة `${VARIABLE:?message}` إلزامي ولن يبدأ النشر قبل إدخاله.

أدخل جميع القيم الموضحة في `ENVIRONMENT_VARIABLES.md`. لا تستخدم القيم التجريبية الموجودة في `.env.example`.

## 3. قاعدة البيانات

مثال `DATABASE_URL`:

```text
postgresql+psycopg://youtube_transcriber:PASSWORD@postgres:5432/youtube_transcriber
```

يجب أن تتطابق كلمة المرور واسم القاعدة والمستخدم مع متغيرات PostgreSQL.

## 4. النطاق

اربط النطاق بخدمة **gateway** على المنفذ `80`. لا تربط نطاقًا بخدمات API أو PostgreSQL أو Redis أو Workers.

فعّل HTTPS. اجعل:

```text
APP_URL=https://your-domain.example
COOKIE_SECURE=true
TRUSTED_HOSTS=your-domain.example
```

## 5. التخزين الدائم

يعرّف Compose الوحدات التالية:

- `postgres-data`
- `redis-data`
- `audio-data`
- `exports-data`
- `youtube-config`

تأكد بعد أول نشر أن Coolify أنشأها ولم يحولها إلى تخزين مؤقت.

## 6. ترتيب بدء الخدمات

1. PostgreSQL وRedis.
2. خدمة migrations.
3. API والعمال الخمسة وScheduler.
4. Gateway بعد نجاح Healthcheck الخاص بالـAPI.

## 7. التحقق بعد النشر

- افتح التطبيق وسجل الدخول.
- افتح صفحة العمال وتأكد من ظهور `worker-1` إلى `worker-5`.
- افتح الإعدادات وتأكد أن عدد مفاتيح Deepgram المضبوطة هو 5.
- ارفع Cookies عند الحاجة.
- جرّب فيديو قصير أولًا.
- جرّب ستة فيديوهات وتأكد أن خمسة تعمل والسادس ينتظر.

## 8. إعادة النشر

إعادة النشر لا تحذف PostgreSQL أو Redis أو التفريغات أو ملفات التصدير. خدمة Alembic تطبق الترحيلات قبل تشغيل النسخة الجديدة.

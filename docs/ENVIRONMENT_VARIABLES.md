# المتغيرات البيئية

## إلزامية

| المتغير | الوصف |
|---|---|
| `APP_URL` | رابط التطبيق الكامل HTTPS |
| `ADMIN_USERNAME` | اسم المدير الوحيد |
| `ADMIN_PASSWORD` | كلمة مرور قوية |
| `SESSION_SECRET` | قيمة عشوائية لا تقل عن 32 حرفًا |
| `POSTGRES_DB` | اسم قاعدة البيانات |
| `POSTGRES_USER` | مستخدم PostgreSQL |
| `POSTGRES_PASSWORD` | كلمة مرور PostgreSQL |
| `DATABASE_URL` | رابط SQLAlchemy إلى خدمة `postgres` |
| `DEEPGRAM_API_KEY_WORKER_1..5` | مفتاح مستقل لكل Worker |

## موصى بها

| المتغير | القيمة المقترحة |
|---|---|
| `APP_ENV` | `production` |
| `TZ` | `Asia/Amman` |
| `COOKIE_SECURE` | `true` |
| `TRUSTED_HOSTS` | اسم النطاق فقط |
| `DEFAULT_LANGUAGE` | `ar` |
| `DEFAULT_DEEPGRAM_MODEL` | `whisper-large` |

## إنشاء Session Secret

```bash
openssl rand -hex 48
```

لا تطبع Coolify الأسرار في السجلات، ولا ترسل ملف `.env` إلى Git.

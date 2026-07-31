# النسخ الاحتياطي والاستعادة

## ما يجب نسخه

1. PostgreSQL.
2. Volume `exports-data`.
3. Volume `youtube-config` إن أردت الاحتفاظ بملف Cookies.
4. Redis اختياري؛ PostgreSQL هو مصدر الحقيقة للمهام والنتائج.

## PostgreSQL

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```

الاستعادة:

```bash
cat backup.sql | docker compose exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

## ملفات التصدير

انسخ Volume `exports-data` أو اربطه بسياسة Backup في Coolify. يجب استعادة قاعدة البيانات والملفات معًا للحفاظ على الروابط بينها.

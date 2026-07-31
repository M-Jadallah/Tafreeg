# YouTube Cookies

## الصيغة المطلوبة

ارفع ملفًا اسمه `cookies.txt` بصيغة Netscape. يجب أن يبدأ بأحد السطرين:

```text
# Netscape HTTP Cookie File
```

أو:

```text
# HTTP Cookie File
```

## الرفع

من صفحة **الإعدادات → YouTube Cookies**:

1. اختر `cookies.txt`.
2. ارفع الملف.
3. اضغط اختبار.
4. اضغط إعادة مهام Cookies لإرجاع المهام المنتظرة إلى الطابور.

## الحماية

- يحفظ الملف في Volume `youtube-config`.
- صلاحياته داخل الحاوية `0600`.
- محتواه لا يحفظ في PostgreSQL.
- محتواه لا يظهر في Logs أو API.

## تحديث yt-dlp

يتطلب YouTube في إصدارات yt-dlp الحديثة Runtime JavaScript خارجيًا. صورة Docker تتضمن Node.js 22 وتثبت مجموعة `yt-dlp[default]` التي تشمل مكونات EJS. عند حدوث تغير عام في YouTube، حدّث نطاق إصدار yt-dlp في `backend/pyproject.toml` وأعد بناء الصور.

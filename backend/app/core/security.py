from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from redis import Redis

from app.core.config import get_settings

settings = get_settings()
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
SESSION_COOKIE = "yt_session"
CSRF_COOKIE = "csrf_token"


def _now() -> datetime:
    return datetime.now(UTC)


def create_session_token(username: str) -> str:
    now = _now()
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_ttl_minutes)).timestamp()),
        "jti": secrets.token_urlsafe(24),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_session_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.session_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="الجلسة غير صالحة") from exc


def set_auth_cookies(response: Response, username: str) -> str:
    token = create_session_token(username)
    csrf = secrets.token_urlsafe(32)
    common = {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": settings.session_ttl_minutes * 60,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)
    try:
        payload = decode_session_token(token)
        redis_client.setex(
            f"admin-session:{payload['jti']}",
            settings.session_idle_minutes * 60,
            username,
        )
    except Exception:
        pass
    return csrf


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def revoke_session_token(token: str | None) -> None:
    if not token:
        return
    try:
        payload = decode_session_token(token)
        jti = str(payload.get("jti", ""))
        if jti:
            redis_client.delete(f"admin-session:{jti}")
    except Exception:
        return


def verify_credentials(username: str, password: str) -> bool:
    username_ok = secrets.compare_digest(username.encode(), settings.admin_username.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    return username_ok and password_ok


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_key(ip: str) -> str:
    return f"login-attempts:{hashlib.sha256(ip.encode()).hexdigest()}"


def check_login_rate_limit(ip: str) -> None:
    try:
        count = redis_client.get(_login_key(ip))
        if count and int(count) >= settings.login_max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="تم تجاوز عدد محاولات الدخول. حاول لاحقًا.",
            )
    except HTTPException:
        raise
    except Exception:
        return


def record_login_failure(ip: str) -> None:
    try:
        key = _login_key(ip)
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.login_window_seconds)
        pipe.execute()
    except Exception:
        pass


def clear_login_failures(ip: str) -> None:
    try:
        redis_client.delete(_login_key(ip))
    except Exception:
        pass


def require_admin(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> str:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="يجب تسجيل الدخول")
    payload = decode_session_token(session)
    username = str(payload.get("sub", ""))
    if not secrets.compare_digest(username.encode(), settings.admin_username.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="الجلسة غير صالحة")
    jti = str(payload.get("jti", ""))
    try:
        key = f"admin-session:{jti}"
        if not redis_client.exists(key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="انتهت الجلسة بسبب الخمول")
        redis_client.expire(key, settings.session_idle_minutes * 60)
    except HTTPException:
        raise
    except Exception:
        pass
    return username


def require_csrf(
    _: str = Depends(require_admin),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> str:
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="رمز حماية الطلب غير صالح")
    return _

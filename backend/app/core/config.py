from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "مفرغ يوتيوب"
    app_env: str = "production"
    app_url: str = "http://localhost:8080"
    app_version: str = "1.0.0"
    timezone: str = "Asia/Amman"
    log_level: str = "INFO"

    admin_username: str
    admin_password: str
    session_secret: str = Field(min_length=32)
    session_ttl_minutes: int = 720
    session_idle_minutes: int = 120

    database_url: str
    redis_url: str = "redis://redis:6379/0"

    worker_name: str = "api"
    deepgram_api_key: str | None = None
    deepgram_api_key_worker_1: str | None = None
    deepgram_api_key_worker_2: str | None = None
    deepgram_api_key_worker_3: str | None = None
    deepgram_api_key_worker_4: str | None = None
    deepgram_api_key_worker_5: str | None = None

    audio_root: Path = Path("/data/audio")
    exports_root: Path = Path("/data/exports")
    youtube_config_root: Path = Path("/data/youtube")
    cookies_filename: str = "cookies.txt"
    audio_retention_hours: int = 24
    audio_bitrate: str = "64k"
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    max_upload_bytes: int = 5 * 1024 * 1024

    default_language: str = "ar"
    default_deepgram_model: str = "whisper-large"
    deepgram_base_url: str = "https://api.deepgram.com/v1/listen"

    cookie_secure: bool = True
    trusted_hosts: str = "*"
    cors_origins: str = ""

    login_max_attempts: int = 5
    login_window_seconds: int = 900

    @field_validator("app_env")
    @classmethod
    def normalize_env(cls, value: str) -> str:
        return value.lower().strip()

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def default_cookie_secure(cls, value: object) -> object:
        return value

    @property
    def cookies_path(self) -> Path:
        return self.youtube_config_root / self.cookies_filename

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def trusted_hosts_list(self) -> list[str]:
        values = [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]
        return values or ["*"]

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        for path in (self.audio_root, self.exports_root, self.youtube_config_root):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.ensure_directories()
    if settings.app_env != "production" and "COOKIE_SECURE" not in __import__("os").environ:
        settings.cookie_secure = False
    return settings

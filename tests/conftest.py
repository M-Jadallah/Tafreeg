from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="ytdg-tests-"))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-password-not-for-production")
os.environ.setdefault("SESSION_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{TEST_ROOT / 'app.db'}")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("AUDIO_ROOT", str(TEST_ROOT / "audio"))
os.environ.setdefault("EXPORTS_ROOT", str(TEST_ROOT / "exports"))
os.environ.setdefault("YOUTUBE_CONFIG_ROOT", str(TEST_ROOT / "youtube"))
os.environ.setdefault("COOKIE_SECURE", "false")

from __future__ import annotations

import time

from sqlalchemy import text

from app.core.db import engine

for attempt in range(60):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database is ready")
        break
    except Exception as exc:
        if attempt == 59:
            raise
        print(f"Waiting for database: {exc}")
        time.sleep(2)

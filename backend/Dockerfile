FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl tini libstdc++6 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

RUN python -m venv /opt/venv
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip setuptools wheel && pip install .
COPY alembic.ini ./
COPY alembic ./alembic
RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /data/audio /data/exports /data/youtube && \
    chown -R appuser:appuser /app /data
USER appuser
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

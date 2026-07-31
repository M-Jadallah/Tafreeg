from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.bulk_exports import router as bulk_exports_router
from app.api.routes import router
from app.core.bootstrap import bootstrap_database
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.errors import WorkflowError

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

app.include_router(router)
app.include_router(bulk_exports_router)


@app.exception_handler(WorkflowError)
async def workflow_error_handler(_: Request, exc: WorkflowError) -> JSONResponse:
    """Return safe, actionable workflow errors without exposing technical details."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.user_message, "code": exc.code, "retryable": exc.retryable},
    )


@app.on_event("startup")
def startup() -> None:
    settings.ensure_directories()
    with SessionLocal() as db:
        bootstrap_database(db)

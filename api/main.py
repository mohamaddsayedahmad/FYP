"""
FastAPI application entry point.

Professional API design choices demonstrated here:
1. Versioned prefix (/api/v1) — enables non-breaking upgrades.
2. Structured startup event — runs DB migrations once before any request.
3. Exception handlers — converts domain exceptions to HTTP responses.
4. CORS configured restrictively (origins from env var, not wildcard *).
5. Auto-generated OpenAPI docs at /docs (Swagger) and /redoc.
6. Request/response logging middleware for observability.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.limiter import limiter
from api.routes import admin, attendance, auth, courses, teachers, users
from core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)

class _JsonFormatter(logging.Formatter):
    """
    Emit one JSON object per log record.

    Standard LogRecord fields are normalised into a fixed schema; any extra
    fields passed via logger.info("msg", extra={...}) are merged in.
    Log aggregators (ELK, Datadog, Cloud Logging) can parse this directly.
    """

    _BASELINE: frozenset = frozenset(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        for key, val in record.__dict__.items():
            if key not in self._BASELINE and key != "message":
                payload[key] = val
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = []
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger(__name__)

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("ATTENDANCE_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:8501").split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run schema migrations before accepting any requests."""
    logger.info("Running database migrations...")
    from infrastructure.database.migrator import run_migrations
    run_migrations()

    logger.info("Ensuring default accounts exist...")
    from api.dependencies import get_auth_service
    get_auth_service().ensure_default_accounts()

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="AI Face Attendance System API",
    description=(
        "REST API for the AI Face Recognition Attendance System.\n\n"
        "**Authentication**: All endpoints except `/api/v1/auth/login` require a "
        "JWT Bearer token. Obtain one via POST `/api/v1/auth/login`.\n\n"
        "**RBAC**: admin > teacher > student. Endpoints document their required role."
    ),
    version="1.0.0",
    contact={
        "name": "Mohamad Ali Sayed Ahmad",
        "email": "moeysayedahmad760@gmail.com",
    },
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---- Request timing middleware ----------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status": response.status_code,
            "duration_ms": round(elapsed, 1),
        },
    )
    return response


# ---- Domain exception handlers ---------------------------------------

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(AuthenticationError)
async def auth_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(AuthorizationError)
async def authz_handler(request: Request, exc: AuthorizationError):
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)}
    )


# ---- Routers ---------------------------------------------------------

PREFIX = "/api/v1"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(admin.router, prefix=PREFIX)
app.include_router(teachers.router, prefix=PREFIX)
app.include_router(users.router, prefix=PREFIX)
app.include_router(courses.router, prefix=PREFIX)
app.include_router(attendance.router, prefix=PREFIX)


@app.get("/", tags=["Health"], summary="Ping")
def ping():
    """Lightweight liveness check — always returns 200 when the process is running."""
    return {"status": "ok", "version": app.version, "docs": "/docs"}


@app.get("/health", tags=["Health"], summary="Health check with DB probe")
def health():
    """
    Readiness probe — checks DB connectivity in addition to process liveness.
    Returns HTTP 200 when healthy, HTTP 503 when the database is unreachable.
    """
    try:
        from infrastructure.database.connection import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "db": "ok", "version": app.version}
    except Exception as exc:
        logger.error("health check failed", extra={"db_error": str(exc)})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "db": "error", "error": str(exc), "version": app.version},
        )

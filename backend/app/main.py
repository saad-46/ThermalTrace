"""ThermalTrace API application factory."""
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.v1 import auth, context, events, monitoring, operations, public, search
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.db.session import engine

configure_logging(settings.log_level, settings.log_json)
logger = logging.getLogger("thermaltrace")
STARTED = datetime.now(UTC)
VERSION = "1.0.0"

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.05, send_default_pii=False)

DESCRIPTION = """
Evidence-based detection, classification and monitoring of thermal anomalies (SIH26162).

**Authentication:** `POST /api/v1/auth/login` → bearer token → `Authorization: Bearer <token>`.
Roles: viewer < analyst < supervisor < admin.

**Errors:** every error has the shape `{"error": {"code", "message", "details", "request_id"}}`.

**Attribution:** NASA FIRMS · © OpenStreetMap contributors (ODbL) · Copernicus Sentinel-2 · Open-Meteo (CC BY 4.0).
"""

app = FastAPI(
    title="ThermalTrace API",
    version=VERSION,
    description=DESCRIPTION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # bearer tokens, no cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestContextMiddleware)
# Large JSON (map GeoJSON, the India boundary) compresses ~5-10x.
app.add_middleware(GZipMiddleware, minimum_size=2048)
install_error_handlers(app)

health = APIRouter(tags=["system"])


@health.get("/health", summary="Liveness: the process is up")
def liveness():
    return {"status": "ok", "version": VERSION, "started_at": STARTED}


@health.get("/ready", summary="Readiness: database reachable and migrated")
def readiness():
    t = time.perf_counter()
    try:
        with engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            conn.execute(text("SELECT postgis_lib_version()"))
    except Exception as exc:
        logger.warning("readiness failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database unavailable or not migrated"})
    return {"status": "ready", "migration": rev, "db_latency_ms": round((time.perf_counter() - t) * 1000, 1)}


@health.get("/metrics", response_class=PlainTextResponse, summary="Prometheus-style operational gauges")
def metrics():
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT (SELECT count(*) FROM thermal_detections) d, (SELECT count(*) FROM thermal_events) e,
                   (SELECT count(*) FROM thermal_events WHERE status='active') a,
                   (SELECT count(*) FROM jobs WHERE status='queued') q, (SELECT count(*) FROM jobs WHERE status='failed') f,
                   (SELECT EXTRACT(EPOCH FROM now() - max(acq_datetime)) FROM thermal_detections WHERE data_mode='live') lag
        """)).one()
    lines = [
        "# TYPE thermaltrace_detections_total gauge", f"thermaltrace_detections_total {r.d}",
        "# TYPE thermaltrace_events_total gauge", f"thermaltrace_events_total {r.e}",
        "# TYPE thermaltrace_events_active gauge", f"thermaltrace_events_active {r.a}",
        "# TYPE thermaltrace_jobs_queued gauge", f"thermaltrace_jobs_queued {r.q}",
        "# TYPE thermaltrace_jobs_failed gauge", f"thermaltrace_jobs_failed {r.f}",
        "# TYPE thermaltrace_firms_latest_detection_age_seconds gauge",
        f"thermaltrace_firms_latest_detection_age_seconds {r.lag or 0:.0f}",
    ]
    return "\n".join(lines) + "\n"


app.include_router(health)
api = APIRouter(prefix="/api/v1")
api.include_router(health)
for module in (auth, events, context, monitoring, operations, public, search):
    api.include_router(module.router)
app.include_router(api)

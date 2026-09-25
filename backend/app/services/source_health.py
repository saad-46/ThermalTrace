"""Tracks health of every external provider (status, latency EWMA, error rate, freshness)."""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ops import DataSource

_EWMA_ALPHA = 0.3


def record_success(db: Session, source_id: str, latency_ms: float | None = None, records: int = 0,
                   last_record_at: datetime | None = None) -> None:
    src = db.get(DataSource, source_id)
    if src is None:
        return
    now = datetime.now(UTC)
    src.status = "healthy"
    src.last_success_at = now
    src.requests_total += 1
    src.records_total += records
    if last_record_at and (src.last_record_at is None or last_record_at > src.last_record_at):
        src.last_record_at = last_record_at
    if latency_ms is not None:
        src.latency_ms_ewma = latency_ms if src.latency_ms_ewma is None else (
            _EWMA_ALPHA * latency_ms + (1 - _EWMA_ALPHA) * src.latency_ms_ewma)


def record_failure(db: Session, source_id: str, error: str) -> None:
    src = db.get(DataSource, source_id)
    if src is None:
        return
    src.requests_total += 1
    src.requests_failed += 1
    src.last_failure_at = datetime.now(UTC)
    src.last_error = error[:1000]
    recent_success = src.last_success_at and (src.last_failure_at - src.last_success_at).total_seconds() < 3600
    src.status = "degraded" if recent_success else "down"


def configuration_state() -> dict[str, dict]:
    """Which providers are usable with the current configuration (credentials never exposed)."""
    return {
        "firms": {"configured": True, "mode": "area_api+nrt_files" if settings.firms_key else "nrt_files_only",
                  "note": None if settings.firms_key else "FIRMS_MAP_KEY not set: historical/Area API disabled; keyless NRT files active"},
        "cdse": {"configured": bool(settings.copernicus_client_id and settings.copernicus_client_secret),
                 "note": "Catalogue search is keyless; SWIR rendering needs COPERNICUS_CLIENT_ID/SECRET"},
        "gem": {"configured": True, "note": "File import — requires a downloaded GEM tracker release"},
        "cea": {"configured": True, "note": "File import — requires a CEA-derived CSV (see data/datasets/README.md)"},
        "email": {"configured": bool(settings.smtp_host and settings.smtp_from)},
        "push": {"configured": bool(settings.vapid_public_key and settings.vapid_private_key)},
        "demo": {"configured": settings.demo_mode},
    }

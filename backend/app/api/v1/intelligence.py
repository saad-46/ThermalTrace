"""Investigation intelligence: filtered dashboard analytics, recurring activity, facility activity profiles, live
system status and data-source detail. Read-only; available to every signed-in role (demo sessions included)."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser
from app.core.errors import AppError, NotFound
from app.db.session import get_db
from app.ml.base import CLASS_LABELS
from app.models.auth import User
from app.schemas.intelligence import EvidenceCoverageOut, FacilityProfileOut, LiveStatusOut, OverviewOut, RecurringOut
from app.services import activity, source_health
from app.services import analytics as A

router = APIRouter()


def analytics_filters(
    days: int | None = Query(None, ge=1, le=3650, description="relative range; ignored when `since` is given"),
    since: datetime | None = None, until: datetime | None = None,
    state: str | None = Query(None, max_length=100), district: str | None = Query(None, max_length=100),
    facility_id: uuid.UUID | None = None, classification: list[str] | None = Query(None),
) -> A.Filters:
    if since and until and since >= until:
        raise AppError("`since` must be before `until`", code="invalid_range")
    if since and until and until - since > timedelta(days=3650):
        raise AppError("The range is limited to 10 years", code="invalid_range")
    unknown = sorted(set(classification or []) - CLASS_LABELS.keys())
    if unknown:
        raise AppError(f"Unknown classification: {', '.join(unknown)[:200]}", code="invalid_classification",
                       details={"allowed": sorted(CLASS_LABELS)})
    return A.Filters.make(days, since, until, state, district, facility_id, sorted(set(classification or [])))


@router.get("/analytics/overview", response_model=OverviewOut, tags=["analytics"],
            summary="Dashboard figures for the selected range and filters (events, review queue, recurring activity, evidence coverage)")
def analytics_overview(f: A.Filters = Depends(analytics_filters), user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached("overview", f, lambda: A.overview(db, f))


@router.get("/analytics/series", tags=["analytics"], summary="Events and detections per day/week/month by classification")
def analytics_series(f: A.Filters = Depends(analytics_filters), user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached("series", f, lambda: A.series(db, f))


@router.get("/analytics/distributions", tags=["analytics"], summary="Classification, persistence, confidence, FRP and duration distributions")
def analytics_distributions(f: A.Filters = Depends(analytics_filters), user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached("distributions", f, lambda: A.distributions(db, f))


@router.get("/analytics/geography", tags=["analytics"], summary="Events by state, district and 1° cell")
def analytics_geography(f: A.Filters = Depends(analytics_filters), user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached("geography", f, lambda: A.geography(db, f))


@router.get("/analytics/evidence-coverage", response_model=EvidenceCoverageOut, tags=["analytics"], summary="How many events have each evidence stage (availability, not confidence)")
def analytics_coverage(f: A.Filters = Depends(analytics_filters), user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached("coverage", f, lambda: A.evidence_coverage(db, f))


@router.get("/analytics/facility-activity", tags=["analytics"], summary="Facilities with the most events within 2 km in the range")
def analytics_facility_activity(f: A.Filters = Depends(analytics_filters), limit: int = Query(20, ge=1, le=100),
                                user: User = CurrentUser, db: Session = Depends(get_db)):
    return A.cached(f"facility-activity-{limit}", f, lambda: A.facility_activity(db, f, limit))


@router.get("/analytics/filter-options", tags=["analytics"], summary="States (and a state's districts) available for filtering")
def analytics_filter_options(state: str | None = Query(None, max_length=100), user: User = CurrentUser, db: Session = Depends(get_db)):
    if state:
        return {"districts": A.districts_for(db, state)}
    now = datetime.now(UTC)
    return A.cached("filter-options", A.Filters(now, now), lambda: A.filter_options(db))


@router.get("/analytics/recurring", response_model=RecurringOut, tags=["analytics"],
            summary="Facilities and places with repeated observed activity (not a risk ranking)")
def analytics_recurring(days: int = Query(7, ge=1, le=365), min_events: int = Query(3, ge=2, le=1000),
                        user: User = CurrentUser, db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    return A.cached(f"recurring-{days}-{min_events}", A.Filters(now - timedelta(days=days), now), lambda: activity.recurring(db, days, min_events))


@router.get("/facilities/{facility_id}/profile", response_model=FacilityProfileOut, tags=["facilities"],
            summary="Facility activity profile: counts, weekly/monthly comparison, thermal distributions, source agreement")
def facility_profile(facility_id: uuid.UUID, within_m: float = Query(2000, ge=100, le=10000), user: User = CurrentUser,
                     db: Session = Depends(get_db)):
    return activity.facility_profile(db, facility_id, within_m)


# --- live system status ----------------------------------------------------------------------------------------------
SOURCE_PURPOSE = {
    "firms": "Active-fire detections (MODIS, VIIRS): the thermal events themselves",
    "osm": "Facilities and land use around events",
    "wri_gppd": "Power plants with fuel and capacity",
    "gem": "Coal and other plant trackers (Global Energy Monitor)",
    "cea": "Official Indian power-station list (Central Electricity Authority)",
    "earth_search": "Sentinel-2 scene search and band windows for NDVI / NBR",
    "cdse": "Copernicus Data Space: optional SWIR renders around an event",
    "open_meteo": "Weather at the event location and time",
    "esa_worldcover": "Land cover shares around events",
    "nominatim": "Reverse geocoding (state, district)",
    "geonames": "Offline place names for events",
}
OPTIONAL = {"cdse": "Only SWIR (B12/B8A/B4) renders need Copernicus credentials; scene search and NDVI / NBR do not.",
            "firms": "Without FIRMS_MAP_KEY only historical / area queries are disabled; near-real-time files work without it."}


def _live_state(eff: str, req: dict, source_id: str) -> tuple[str, str]:
    if eff == "active":
        return "healthy", "Healthy"
    if eff == "unverified":
        return "configured", "Configured"
    if eff == "not_used":
        return ("optional", "Optional") if source_id in OPTIONAL else ("configured", "Configured, not used yet")
    if eff == "degraded":
        return "degraded", "Degraded"
    if eff == "unavailable":
        return "failed", "Failed"
    if eff == "credentials_required":
        return ("optional", "Optional, not configured") if source_id in OPTIONAL or req.get("optional") else ("not_configured", "Not configured")
    if eff == "import_required":
        return "no_data", "No data imported"
    return "configured", eff.replace("_", " ")


def _sources(db: Session) -> list[dict]:
    cfg = source_health.configuration_state()
    rows = db.execute(text("""SELECT id, name, kind, access, status, last_success_at, last_failure_at, last_error, records_total,
                                     requests_total, requests_failed, latency_ms_ewma, health_detail
                              FROM data_sources WHERE id <> 'demo' ORDER BY kind, id""")).mappings().all()
    out = []
    for r in rows:
        eff = source_health.effective_state(r["id"], r["status"], r["access"], r["last_success_at"] is not None, cfg, r["health_detail"])
        req = source_health.REQUIREMENTS.get(r["id"], {})
        status, label = _live_state(eff["state"], req, r["id"])
        out.append({**dict(r), "status": status, "label": label, "requires_credentials": req.get("type") == "credentials",
                    "optional": r["id"] in OPTIONAL or bool(req.get("optional")), "effective": eff})
    return out


@router.get("/status/live", response_model=LiveStatusOut, tags=["system"],
            summary="Expandable live status: every source's state, job queue, and the last FIRMS / weather / imagery updates")
def live_status(user: User = CurrentUser, db: Session = Depends(get_db)):
    srcs = _sources(db)
    r = db.execute(text("""
        SELECT (SELECT max(completed_at) FROM ingestion_runs WHERE source_id = 'firms' AND status IN ('success', 'partial')) AS firms,
               (SELECT max(retrieved_at) FROM weather_observations) AS weather,
               (SELECT max(retrieved_at) FROM satellite_observations) AS satellite,
               (SELECT count(*) FROM jobs WHERE status = 'running') AS running,
               (SELECT count(*) FROM jobs WHERE status = 'queued') AS queued,
               (SELECT count(*) FROM jobs WHERE status = 'failed' AND finished_at > now() - interval '24 hours') AS failed_24h,
               (SELECT json_agg(x) FROM (SELECT kind, status, started_at FROM jobs WHERE status = 'running' ORDER BY started_at LIMIT 10) x) AS running_jobs,
               (SELECT max(last_seen_at) FROM worker_heartbeats) AS worker_seen""")).mappings().one()
    failed = [s for s in srcs if s["last_failure_at"]]
    last_failed = max(failed, key=lambda s: s["last_failure_at"]) if failed else None
    return {
        "sources": srcs, "sources_active": sum(1 for s in srcs if s["status"] == "healthy"), "sources_total": len(srcs),
        "jobs": {"running": r["running"], "queued": r["queued"], "failed_24h": r["failed_24h"], "running_jobs": r["running_jobs"] or []},
        "last_firms_update": r["firms"], "last_weather_update": r["weather"], "last_satellite_search": r["satellite"],
        "last_failed_source": ({"id": last_failed["id"], "name": last_failed["name"], "at": last_failed["last_failure_at"],
                                "category": error_category_text(last_failed["last_error"])} if last_failed else None),
        "worker_online": r["worker_seen"] is not None and r["worker_seen"] > datetime.now(UTC) - timedelta(minutes=3),
    }


_CATEGORIES = (
    (re.compile(r"timeout|timed out"), "timeout"),
    (re.compile(r"rate.?limit|\b429\b|too many requests"), "rate_limited"),
    (re.compile(r"\bauth|\b401\b|\b403\b|unauthori[sz]ed|forbidden|credential"), "authentication_failed"),
    (re.compile(r"\b5\d\d\b|server error|service unavailable|bad gateway"), "service_unavailable"),
    (re.compile(r"network|connect|dns|unreachable|reset by peer"), "network_error"),
    (re.compile(r"malformed|invalid json|unexpected response"), "invalid_response"),
    (re.compile(r"\b404\b|not found"), "unsupported_data"),
)


def error_category_text(message: str | None) -> str | None:
    """A stored provider error reduced to a category (the raw message may contain URLs; it stays in the logs)."""
    if not message:
        return None
    m = message.lower().strip()
    if m.startswith("[") and "]" in m:  # recorded with its category (source_health.record_failure)
        m = m[1:m.index("]")]
    if m in source_health.ERROR_CATEGORIES or m in ("network_error", "invalid_response"):
        return m
    return next((cat for rx, cat in _CATEGORIES if rx.search(m)), "provider_error")  # older, uncategorised messages


@router.get("/sources/{source_id}/detail", tags=["sources"], summary="One provider: purpose, authentication requirement, health, freshness")
def source_detail(source_id: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    src = next((s for s in _sources(db) if s["id"] == source_id), None)
    if src is None:
        raise NotFound("Source not found")
    req = source_health.REQUIREMENTS.get(source_id, {})
    auth = ("No API key required." if not src["requires_credentials"] and src["access"] in ("api", "file_import")
            else req.get("label") or "Credentials required")
    category = error_category_text(src["last_error"])
    return {
        "id": src["id"], "name": src["name"], "kind": src["kind"], "purpose": SOURCE_PURPOSE.get(source_id), "access": src["access"],
        "authentication": auth, "optional": src["optional"], "optional_detail": OPTIONAL.get(source_id),
        "status": src["status"], "label": src["label"], "reason": src["effective"]["reason"],
        "last_success_at": src["last_success_at"], "last_failure_at": src["last_failure_at"], "last_error_category": category,
        "records_total": src["records_total"], "requests_total": src["requests_total"], "requests_failed": src["requests_failed"],
        "latency_ms": round(src["latency_ms_ewma"]) if src["latency_ms_ewma"] is not None else None,
        "rate_limit": "rate-limited at the last failure" if category == "rate_limited" else "no rate limiting recorded",
        "checks": src["health_detail"] or None,
    }

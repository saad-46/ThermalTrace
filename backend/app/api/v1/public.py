"""Public, unauthenticated aggregates for the landing page.

Only totals, source states and a coarse activity grid are exposed: no event ids, coordinates of individual events,
users, notes, reviews, credentials or configuration values. Computed at most once per cache window (anonymous
requests are also rate-limited per IP by the middleware). Disable with PUBLIC_LANDING_ENABLED=false.
"""
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFound
from app.db.session import get_db
from app.gis import boundaries
from app.ml.rule_cascade import MODEL_ID as RULE_MODEL_ID
from app.services.source_health import configuration_state, effective_state

router = APIRouter(prefix="/public", tags=["public"])
logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
ACTIVITY_DAYS = 30
CELL_DEG = 0.25  # ~25 km: shows where anomalies are without exposing individual event positions

_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


class PublicCounts(BaseModel):
    """India only: events inside India's boundary (and their detections)."""
    detections: int
    events: int
    events_recent: int
    facilities: int
    events_outside_india: int  # excluded from every India figure (neighbouring countries)


class PublicSource(BaseModel):
    id: str
    name: str
    kind: str
    # active | degraded | unavailable | credentials_required | import_required | not_used
    state: str
    reason: str
    requirement: str | None = None
    last_success_at: datetime | None
    checks: dict | None = None  # per-capability checks, e.g. Copernicus {"auth": {...}, "preview": {...}}
    dataset_version: str | None = None
    dataset_published_at: datetime | None = None
    registry: dict | None = None  # station registries (CEA): listed / located / ambiguous / unmatched


class PublicActivity(BaseModel):
    window_days: int
    cell_deg: float
    cells: list[tuple[float, float, int]]  # (cell-centre latitude, cell-centre longitude, events)


class PublicLanding(BaseModel):
    counts: PublicCounts
    sources: list[PublicSource]
    sources_active: int
    sources_total: int
    latest_detection: datetime | None
    firms_last_sync: datetime | None
    workers_online: bool
    classifier: str
    activity: PublicActivity
    generated_at: datetime
    cache_seconds: int


def _compute(db: Session) -> dict:
    c = db.execute(text("""
        SELECT (SELECT coalesce(sum(observation_count), 0) FROM thermal_events   -- = detections of those events
                 WHERE data_mode <> 'demo' AND in_india IS NOT FALSE) AS detections,
               (SELECT count(*) FROM thermal_events WHERE data_mode <> 'demo' AND in_india IS NOT FALSE) AS events,
               (SELECT count(*) FROM thermal_events WHERE data_mode <> 'demo' AND in_india IS NOT FALSE
                  AND last_detected >= now() - make_interval(days => :days)) AS events_recent,
               (SELECT count(*) FROM thermal_events WHERE data_mode <> 'demo' AND in_india IS FALSE) AS events_outside_india,
               (SELECT count(*) FROM facilities f WHERE EXISTS (
                  SELECT 1 FROM boundary_parts b WHERE b.code = 'IND' AND ST_Intersects(b.geom, f.geom::geometry))) AS facilities,
               (SELECT max(acq_datetime) FROM thermal_detections WHERE data_mode <> 'demo') AS latest_detection,
               (SELECT max(completed_at) FROM ingestion_runs WHERE source_id = 'firms' AND status IN ('success', 'partial'))
                  AS firms_last_sync,
               (SELECT max(last_seen_at) FROM worker_heartbeats) AS worker_seen"""), {"days": ACTIVITY_DAYS}).mappings().one()
    cfg = configuration_state()
    # Registries imported station by station (CEA): what was listed, and how much of it could be located.
    registries = {row.source_id: {"stations": row.stations, "located": row.located, "ambiguous": row.ambiguous,
                                  "unmatched": row.unmatched, "facilities": row.facilities, "units": row.units,
                                  "capacity_mw": round(row.capacity_mw or 0, 1), "imported_at": row.imported_at,
                                  "coordinate_sources": row.coordinate_sources}
                  for row in db.execute(text("""
        SELECT source_id, count(*) AS stations, count(facility_id) AS located,
               count(*) FILTER (WHERE match_status = 'ambiguous') AS ambiguous,
               count(*) FILTER (WHERE match_status = 'unmatched') AS unmatched,
               count(DISTINCT facility_id) AS facilities, sum(unit_count) AS units, sum(capacity_mw) AS capacity_mw,
               max(imported_at) AS imported_at,
               array_remove(array_agg(DISTINCT coordinate_source), NULL) AS coordinate_sources
        FROM registry_stations GROUP BY source_id""")).all()}
    sources = []
    for r in db.execute(text("SELECT id, name, kind, access, status, last_success_at, health_detail, dataset_version, "
                             "dataset_published_at FROM data_sources WHERE id <> 'demo' ORDER BY kind, id")).all():
        eff = effective_state(r.id, r.status, r.access, r.last_success_at is not None, cfg, r.health_detail)
        checks = {k: {f: v.get(f) for f in ("ok", "checked_at", "latency_ms", "error", "last_success_at")}
                  for k, v in (r.health_detail or {}).items()}
        sources.append({"id": r.id, "name": r.name, "kind": r.kind, "last_success_at": r.last_success_at,
                        "state": eff["state"], "reason": eff["reason"], "requirement": eff["requirement"],
                        "checks": checks or None, "dataset_version": r.dataset_version,
                        "dataset_published_at": r.dataset_published_at, "registry": registries.get(r.id)})
    cells = db.execute(text("""
        SELECT (floor(latitude / :d) + 0.5) * :d AS lat, (floor(longitude / :d) + 0.5) * :d AS lon, count(*) AS n
        FROM thermal_events
        WHERE data_mode <> 'demo' AND in_india IS NOT FALSE AND last_detected >= now() - make_interval(days => :days)
        GROUP BY 1, 2 ORDER BY 3 DESC"""), {"d": CELL_DEG, "days": ACTIVITY_DAYS}).all()
    # Classifier of record, decided as in app.ml.registry: an activated LightGBM model whose artifact exists,
    # otherwise the rule cascade.
    gbm = db.execute(text("SELECT id, artifact_path FROM model_versions WHERE kind = 'lightgbm' AND is_active LIMIT 1")).first()
    classifier = gbm.id if gbm and gbm.artifact_path and Path(gbm.artifact_path).exists() else RULE_MODEL_ID
    seen = c["worker_seen"]
    return {
        "counts": {k: c[k] for k in ("detections", "events", "events_recent", "facilities", "events_outside_india")},
        "sources": sources,
        "sources_active": sum(1 for s in sources if s["state"] == "active"),
        "sources_total": len(sources),
        "latest_detection": c["latest_detection"],
        "firms_last_sync": c["firms_last_sync"],
        "workers_online": seen is not None and seen > datetime.now(UTC) - timedelta(minutes=3),
        "classifier": classifier,
        "activity": {"window_days": ACTIVITY_DAYS, "cell_deg": CELL_DEG,
                     "cells": [(round(r.lat, 2), round(r.lon, 2), r.n) for r in cells]},
        "generated_at": datetime.now(UTC),
        "cache_seconds": CACHE_SECONDS,
    }


@router.get("/landing", response_model=PublicLanding,
            summary="Public landing-page aggregates: totals, source states, 30-day activity on a 1° grid (no identifiers)")
def landing(db: Session = Depends(get_db)):
    if not settings.public_landing_enabled:
        raise NotFound("Not found")
    with _lock:
        data, fresh = _cache["data"], time.monotonic() - _cache["at"] < CACHE_SECONDS
        if data is not None and not fresh and not _cache.get("refreshing"):
            # Serve the previous snapshot (it carries generated_at) and refresh it in the background, so no visitor
            # waits for the aggregate queries after the first one.
            _cache["refreshing"] = True
            threading.Thread(target=_refresh_in_background, daemon=True, name="public-landing-refresh").start()
    if data is not None:
        return data
    data = _compute(db)
    with _lock:
        _cache.update(at=time.monotonic(), data=data)
    return data


def _refresh_in_background() -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        data = _compute(db)
        with _lock:
            _cache.update(at=time.monotonic(), data=data)
    except Exception:  # keep serving the previous snapshot; the next request retries
        logger.warning("public landing refresh failed", exc_info=True)
    finally:
        with _lock:
            _cache["refreshing"] = False
        db.close()


def clear_cache() -> None:
    with _lock:
        _cache.update(at=0.0, data=None, refreshing=False)


_boundary_cache: dict = {}
_DETAIL = {"overview": 0.02, "map": 0.004}


@router.get("/boundary", summary="India outline (Natural Earth, India point of view), mask of everything else, state lines")
def boundary(response: Response, detail: Literal["overview", "map"] = "map", db: Session = Depends(get_db)):
    if not settings.public_landing_enabled:
        raise NotFound("Not found")
    loaded = db.execute(text("SELECT loaded_at FROM boundaries WHERE code = 'IND'")).scalar()
    if loaded is None:
        raise NotFound("The India boundary is not loaded")
    key = (detail, loaded)
    with _lock:
        cached = _boundary_cache.get(key)
    if cached is None:
        cached = boundaries.boundary_geojson(db, _DETAIL[detail])
        with _lock:
            _boundary_cache.clear() if len(_boundary_cache) > 8 else None
            _boundary_cache[key] = cached
    response.headers["Cache-Control"] = "public, max-age=86400"
    return cached


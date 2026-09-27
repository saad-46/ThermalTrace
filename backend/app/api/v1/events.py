from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import AnalystUser, CurrentUser, Page, SupervisorUser, pagination
from app.core.errors import AppError, Conflict
from app.db.session import get_db
from app.gis.geo import bbox_from_string
from app.models.auth import User
from app.processing.confidence import REVIEW_STATUSES
from app.processing.pipeline import analyse_event
from app.repositories import events as repo
from app.schemas.api import AssignIn, EventDetail, EventSummary, FeaturedEvent, NoteIn, ReviewIn, SimilarEvent
from app.schemas.api import Page as PageOut
from app.schemas.intelligence import ClusterOut, CompareOut, RecurrenceOut
from app.services import audit, reviews
from app.workers.queue import enqueue

router = APIRouter(prefix="/events", tags=["events"])


def event_filters(
    bbox: str | None = Query(None, description="west,south,east,north (WGS84)"),
    since: datetime | None = Query(None, description="events with detections on/after this time"),
    until: datetime | None = None,
    classification: list[str] | None = Query(None),
    persistence: list[str] | None = Query(None),
    confidence_state: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    review_status: list[str] | None = Query(None),
    data_mode: list[str] | None = Query(None),
    data_quality: list[str] | None = Query(None),
    sensor: list[str] | None = Query(None),
    facility_type: list[str] | None = Query(None),
    min_frp: float | None = Query(None, ge=0),
    min_confidence: float | None = Query(None, ge=0, le=1),
    min_observations: int | None = Query(None, ge=1),
    min_priority: float | None = Query(None, ge=0, le=100, description="triage priority 0-100"),
    assigned_to: str | None = None,
    q: str | None = Query(None, max_length=100),
    region: Literal["india", "all"] = Query("india", description="india (default): only events inside India's boundary"),
) -> dict:
    try:
        parsed_bbox = bbox_from_string(bbox) if bbox else None
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_bbox") from None
    unknown = sorted(set(review_status or []) - set(REVIEW_STATUSES))
    if unknown:
        raise AppError(f"Unknown review status: {', '.join(unknown)[:200]}", code="invalid_review_status",
                       details={"allowed": list(REVIEW_STATUSES)})
    return dict(bbox=parsed_bbox, since=since, until=until, classification=classification, persistence=persistence,
                confidence_state=confidence_state, status=status, review_status=review_status, data_mode=data_mode,
                data_quality=data_quality, sensor=sensor, facility_type=facility_type, min_frp=min_frp,
                min_confidence=min_confidence, min_observations=min_observations, min_priority=min_priority, assigned_to=assigned_to, q=q,
                region=region)


@router.get("", response_model=PageOut[EventSummary], summary="List thermal events (filterable, paginated)")
def list_events(filters: dict = Depends(event_filters), sort: str = Query("last_detected", pattern="^(" + "|".join(repo.SORTS) + ")$"),
                page: Page = Depends(pagination), user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total = repo.list_events(db, filters, sort, page.limit, page.offset)
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/geojson", summary="Viewport-bounded GeoJSON of events for the map")
def events_geojson(filters: dict = Depends(event_filters), limit: int = Query(3000, ge=1, le=10000),
                   user: User = CurrentUser, db: Session = Depends(get_db)):
    return repo.events_geojson(db, filters, limit)


@router.get("/nearest", response_model=EventSummary | None, summary="Nearest event to a point (within max_km)")
def nearest(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), max_km: float = Query(50, gt=0, le=500),
            user: User = CurrentUser, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT id FROM thermal_events WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, :r) "
                          "ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography LIMIT 1"),
                     {"lat": lat, "lon": lon, "r": max_km * 1000}).scalar()
    if row is None:
        return None
    return repo.get_summary(db, row)


@router.get("/featured", response_model=FeaturedEvent | None,
            summary="The real event carrying the most evidence (used by the guided tour), with what is and is not available")
def featured(user: User = CurrentUser, db: Session = Depends(get_db)):
    return repo.featured_event(db)


@router.get("/compare", response_model=CompareOut,
            summary="Two events side by side for investigation (facts only: no ranking, no winner)")
def compare(a: str = Query(..., max_length=64), b: str = Query(..., max_length=64), user: User = CurrentUser,
            db: Session = Depends(get_db)):
    from app.services import investigation

    ea, eb = repo.resolve_event_id(db, a), repo.resolve_event_id(db, b)
    if ea == eb:
        raise AppError("Choose two different events", code="same_event")
    dist = db.execute(text("SELECT ST_Distance(x.geom, y.geom) FROM thermal_events x, thermal_events y WHERE x.id = :a AND y.id = :b"),
                      {"a": ea, "b": eb}).scalar_one()
    return {"a": investigation.compare_record(repo.get_bundle(db, ea)), "b": investigation.compare_record(repo.get_bundle(db, eb)),
            "distance_m": dist,
            "note": "A side-by-side view of recorded evidence. It does not rank the events or imply that they share a cause."}


@router.get("/{ref}/cluster", response_model=ClusterOut,
            summary="Events near this one in space and time (activity cluster); not a shared source or cause")
def event_cluster(ref: str, radius_km: float = Query(5, gt=0, le=25), days: int = Query(30, ge=0, le=365),
                  user: User = CurrentUser, db: Session = Depends(get_db)):
    from app.services import activity

    return activity.cluster(db, repo.resolve_event_id(db, ref), radius_km, days)


@router.get("/{ref}/recurrence", response_model=RecurrenceOut,
            summary="Recurring activity around this event's location: this week, previous week, 30-day windows, history")
def event_recurrence(ref: str, radius_km: float = Query(2, gt=0, le=25), user: User = CurrentUser, db: Session = Depends(get_db)):
    from app.services import activity

    return activity.recurrence_at(db, repo.resolve_event_id(db, ref), radius_km)


@router.get("/{ref}", response_model=EventDetail, summary="Full investigation bundle for one event (id or public id)")
def get_event(ref: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    bundle = repo.get_bundle(db, repo.resolve_event_id(db, ref), user.id)
    if user.is_demo:
        from app.services.explore import mask_pii

        bundle = mask_pii(bundle)
    return bundle


@router.get("/{ref}/similar", response_model=list[SimilarEvent],
            summary="Historically similar events by thermal fingerprint, with why each is considered similar (not a shared cause)")
def similar(ref: str, limit: int = Query(8, ge=1, le=50), user: User = CurrentUser, db: Session = Depends(get_db)):
    return repo.similar_events(db, repo.resolve_event_id(db, ref), limit)


@router.get("/{ref}/detections.geojson", summary="Individual FIRMS pixels of an event (replay / map layer)")
def detections_geojson(ref: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    eid = repo.resolve_event_id(db, ref)
    # bounded: a long-lived event can hold many thousands of pixels; the most recent 5,000 are returned
    rows = db.execute(text("SELECT * FROM (SELECT id, longitude, latitude, acq_datetime, satellite, dataset, frp, daynight, "
                           "confidence_raw FROM thermal_detections WHERE event_id = :id ORDER BY acq_datetime DESC LIMIT 5001) d "
                           "ORDER BY acq_datetime"), {"id": eid}).mappings().all()
    truncated = len(rows) > 5000
    rows = rows[1:] if truncated else rows
    return {"type": "FeatureCollection", "truncated": truncated, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
         "properties": {"id": str(r["id"]), "t": r["acq_datetime"].isoformat(), "satellite": r["satellite"],
                        "dataset": r["dataset"], "frp": r["frp"], "daynight": r["daynight"], "confidence": r["confidence_raw"]}}
        for r in rows]}


@router.post("/{ref}/reviews", status_code=201, summary="Record an analyst decision (confirm/reject/false positive/escalate/reclassify/note)")
def create_review(ref: str, body: ReviewIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    eid = repo.resolve_event_id(db, ref)
    before = db.execute(text("SELECT review_status, classification FROM thermal_events WHERE id=:i"), {"i": eid}).one()
    review = reviews.record_review(db, eid, body, user)
    after = db.execute(text("SELECT review_status FROM thermal_events WHERE id=:i"), {"i": eid}).scalar()
    audit.record(db, request, user.id, f"event.review.{body.decision}", "event", eid, {
        **body.model_dump(exclude_none=True),
        "previous": {"review_status": before.review_status, "system_class": before.classification},
        "new": {"review_status": after, "analyst_class": review.source_class},
    })
    db.commit()
    return {"id": review.id, "review_status": db.execute(text("SELECT review_status FROM thermal_events WHERE id=:i"), {"i": eid}).scalar()}


@router.post("/{ref}/notes", status_code=201, summary="Add a note or evidence link")
def create_note(ref: str, body: NoteIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    eid = repo.resolve_event_id(db, ref)
    note = reviews.add_note(db, eid, body, user)
    audit.record(db, request, user.id, "event.note", "event", eid)
    db.commit()
    return {"id": note.id}


@router.post("/{ref}/assign", summary="Assign the event's investigation to an analyst")
def assign(ref: str, body: AssignIn, request: Request, user: User = SupervisorUser, db: Session = Depends(get_db)):
    eid = repo.resolve_event_id(db, ref)
    previous = db.execute(text("SELECT assigned_to, priority FROM investigations WHERE event_id = :e"), {"e": eid}).mappings().first()
    inv = reviews.assign(db, eid, body, user)
    audit.record(db, request, user.id, "event.assign", "event", eid,
                 {"previous": {"assignee": str(previous["assigned_to"]) if previous and previous["assigned_to"] else None,
                               "priority": previous["priority"] if previous else None},
                  "new": {"assignee": str(body.user_id) if body.user_id else None, "priority": body.priority}})
    db.commit()
    return {"investigation_id": inv.id, "assigned_to": inv.assigned_to}


@router.post("/{ref}/imagery-analysis", status_code=202,
             summary="Queue Sentinel-2 NDVI/NBR change analysis (before vs after scenes) for this event")
def request_imagery_analysis(ref: str, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    from sqlalchemy import select

    from app.models.enrichment import SatelliteObservation
    from app.models.thermal import ThermalEvent
    from app.services import imagery

    eid = repo.resolve_event_id(db, ref)
    ev = db.get(ThermalEvent, eid)
    scenes = list(db.execute(select(SatelliteObservation).where(SatelliteObservation.event_id == eid)).scalars())
    ready, why = imagery.readiness(ev, scenes)
    if not ready:  # nothing to compare: never queue a computation that cannot produce a result
        raise Conflict(why, code="imagery_not_ready")
    job_id = enqueue(db, "imagery_analysis", {"event_id": str(eid)}, dedupe_key=f"imagery:{eid}", priority=12, created_by=user.id)
    audit.record(db, request, user.id, "event.imagery_analysis.request", "event", eid, {"job": str(job_id)})
    db.commit()
    return {"job_id": job_id}


@router.post("/{ref}/enrich", status_code=202,
             summary="Queue enrichment for this event: every step, or only `steps` (osm, landcover, weather, satellite, geocode)")
def enrich(ref: str, request: Request, steps: list[str] | None = Query(None), user: User = AnalystUser,
           db: Session = Depends(get_db)):
    from app.services.enrichment import STEPS

    wanted = sorted(set(steps)) if steps else list(STEPS)
    unknown = set(wanted) - set(STEPS)
    if unknown:
        raise AppError(f"Unknown enrichment steps: {', '.join(sorted(unknown))}", code="invalid_steps")
    eid = repo.resolve_event_id(db, ref)
    payload = {"event_id": str(eid)} if not steps else {"event_id": str(eid), "steps": wanted}
    job_id = enqueue(db, "enrich_event", payload, dedupe_key=f"enrich:{eid}:{','.join(wanted)}", priority=10, created_by=user.id)
    audit.record(db, request, user.id, "event.enrich.request", "event", eid, {"job": str(job_id), "steps": wanted})
    db.commit()
    return {"job_id": job_id, "steps": wanted}


@router.post("/{ref}/reanalyse", summary="Re-run classification with current context (synchronous, fast)")
def reanalyse(ref: str, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    eid = repo.resolve_event_id(db, ref)
    before = db.execute(text("SELECT classification, confidence_state FROM thermal_events WHERE id = :i"), {"i": eid}).mappings().one()
    cls = analyse_event(db, eid)
    audit.record(db, request, user.id, "event.reanalyse", "event", eid,
                 {"previous": dict(before), "new": {"classification": cls.source_class, "confidence_state": cls.confidence_state}})
    db.commit()
    return {"classification": cls.source_class, "confidence_state": cls.confidence_state, "confidence_score": cls.confidence_score}

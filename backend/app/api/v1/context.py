"""Facilities, satellite imagery, weather and push-subscription endpoints."""
import time
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import AnalystUser, CurrentUser, Page, pagination
from app.core.errors import AppError, NotFound, ProviderNotConfigured, SourceUnavailable
from app.db import like as like_pattern
from app.db.session import get_db
from app.gis.geo import bbox_from_string
from app.integrations.http import ProviderError
from app.integrations.sentinel import SatellitePreviewService
from app.integrations.weather import WeatherClient
from app.models.auth import PushSubscription, User
from app.models.enrichment import SatelliteObservation
from app.repositories.events import _with_display
from app.schemas.api import FacilityOut, PushSubscriptionIn
from app.schemas.api import Page as PageOut
from app.services import audit, source_health

router = APIRouter()

_FAC_COLS = """f.id, f.name, f.facility_type, f.operator, f.status, f.capacity_value, f.capacity_unit, f.state, f.district,
               f.latitude, f.longitude, f.confidence, f.primary_source, f.source_count"""


def _fac_filters(bbox: str | None, facility_type: list[str] | None, source: str | None, q: str | None) -> tuple[str, dict]:
    clauses, params = ["1=1"], {}
    if bbox:
        try:
            w, s, e, n = bbox_from_string(bbox)
        except ValueError as exc:
            raise AppError(str(exc), code="invalid_bbox") from None
        clauses.append("f.geom && ST_MakeEnvelope(:w,:s,:e,:n,4326)::geography")
        params.update(w=w, s=s, e=e, n=n)
    if facility_type:
        clauses.append("f.facility_type = ANY(:ft)")
        params["ft"] = facility_type
    if source:
        clauses.append("EXISTS (SELECT 1 FROM facility_sources fs WHERE fs.facility_id = f.id AND fs.source_id = :src)")
        params["src"] = source
    if q:
        clauses.append("(f.name ILIKE :q OR f.operator ILIKE :q)")
        params["q"] = like_pattern.contains(q)
    return " AND ".join(clauses), params


@router.get("/facilities", response_model=PageOut[FacilityOut], tags=["facilities"])
def list_facilities(bbox: str | None = None, facility_type: list[str] | None = Query(None), source: str | None = None,
                    q: str | None = Query(None, max_length=100), with_events: bool = False,
                    page: Page = Depends(pagination), user: User = CurrentUser, db: Session = Depends(get_db)):
    where, params = _fac_filters(bbox, facility_type, source, q)
    total = db.execute(text(f"SELECT count(*) FROM facilities f WHERE {where}"), params).scalar_one()
    order = "event_count DESC NULLS LAST, f.name" if with_events else "f.name NULLS LAST"
    rows = db.execute(text(f"""
        SELECT {_FAC_COLS}, (SELECT count(*) FROM event_facility_links l WHERE l.facility_id = f.id AND l.distance_m <= 3000) AS event_count
        FROM facilities f WHERE {where} ORDER BY {order} LIMIT :limit OFFSET :offset"""),
        {**params, "limit": page.limit, "offset": page.offset}).mappings().all()
    return {"items": [dict(r) for r in rows], "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/facilities/geojson", tags=["facilities"], summary="Facilities in a viewport, for the map layer")
def facilities_geojson(bbox: str = Query(...), facility_type: list[str] | None = Query(None), limit: int = Query(4000, ge=1, le=10000),
                       user: User = CurrentUser, db: Session = Depends(get_db)):
    where, params = _fac_filters(bbox, facility_type, None, None)
    rows = db.execute(text(f"SELECT {_FAC_COLS}, f.subtype, f.attributes->'registries'->0 AS registry "
                           f"FROM facilities f WHERE {where} LIMIT :limit"), {**params, "limit": limit + 1}).mappings().all()
    return {"type": "FeatureCollection", "truncated": len(rows) > limit, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
         "properties": {"id": str(r["id"]), "name": r["name"], "type": r["facility_type"], "source": r["primary_source"],
                        "sources": r["source_count"], "confidence": r["confidence"], "status": r["status"],
                        "subtype": r["subtype"], "capacity": r["capacity_value"], "capacity_unit": r["capacity_unit"],
                        "operator": r["operator"],
                        # CEA registry entry (identity) and where its coordinates came from
                        "registry": r["registry"].get("source") if r["registry"] else None,
                        "registry_station": r["registry"].get("station") if r["registry"] else None,
                        "coordinate_source": r["registry"].get("coordinate_source") if r["registry"] else None}}
        for r in rows[:limit]]}


@router.get("/facilities/{facility_id}", response_model=FacilityOut, tags=["facilities"])
def get_facility(facility_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    row = db.execute(text(f"""SELECT {_FAC_COLS}, f.subtype, f.attributes->'registries' AS registries,
        (SELECT count(*) FROM event_facility_links l WHERE l.facility_id = f.id AND l.distance_m <= 3000) AS event_count,
        (SELECT json_agg(json_build_object('source', s.source_id, 'external_id', s.external_id, 'name', s.name,
            'source_type', s.source_type, 'url', s.source_url, 'dataset_version', s.dataset_version,
            'published_at', s.published_at, 'retrieved_at', s.retrieved_at)) FROM facility_sources s WHERE s.facility_id = f.id) AS sources
        FROM facilities f WHERE f.id = :id"""), {"id": facility_id}).mappings().first()
    if row is None:
        raise NotFound("Facility not found")
    return dict(row)


@router.get("/facilities/{facility_id}/events", tags=["facilities"], summary="Facility-level thermal history (paginated)")
def facility_events(facility_id: uuid.UUID, within_m: float = Query(3000, ge=100, le=10000),
                    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100_000),
                    user: User = CurrentUser, db: Session = Depends(get_db)):
    total = db.execute(text("SELECT count(*) FROM event_facility_links l WHERE l.facility_id = :id AND l.distance_m <= :w"),
                       {"id": facility_id, "w": within_m}).scalar_one()
    # one page of events; peak brightness per event from its own detections (index on thermal_detections.event_id)
    rows = db.execute(text("""
        SELECT e.id, e.public_id, e.first_detected, e.last_detected, e.classification, e.persistence_class,
               e.persistence_score, e.confidence_state, e.confidence_score, e.priority_score, e.review_status, e.status,
               e.observation_count, e.frp_max, e.latitude, e.longitude, l.distance_m, l.attribution_score, l.rank,
               (SELECT max(d.brightness) FROM thermal_detections d WHERE d.event_id = e.id) AS brightness_max
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w ORDER BY e.last_detected DESC LIMIT :limit OFFSET :offset"""),
        {"id": facility_id, "w": within_m, "limit": limit, "offset": offset}).mappings().all()
    weekly = db.execute(text("""
        SELECT date_trunc('week', d.acq_datetime) AS week, count(*) AS detections, max(d.frp) AS frp_max
        FROM event_facility_links l JOIN thermal_detections d ON d.event_id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w GROUP BY 1 ORDER BY 1"""), {"id": facility_id, "w": within_m}).mappings().all()
    profile = db.execute(text("""
        SELECT count(DISTINCT e.id) AS events,
               count(DISTINCT e.id) FILTER (WHERE e.persistence_class = 'persistent') AS persistent,
               count(DISTINCT e.id) FILTER (WHERE e.status = 'active') AS active,
               count(DISTINCT e.id) FILTER (WHERE e.review_status = 'analyst_confirmed') AS analyst_confirmed,
               COALESCE(sum(e.observation_count), 0) AS detections, max(e.frp_max) AS frp_max,
               min(e.first_detected) AS first_activity, max(e.last_detected) AS last_activity
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w"""), {"id": facility_id, "w": within_m}).mappings().one()
    classes = db.execute(text("""
        SELECT COALESCE(e.classification, 'unprocessed') AS classification, count(*) AS n
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w GROUP BY 1 ORDER BY 2 DESC"""), {"id": facility_id, "w": within_m}).mappings().all()
    prof = dict(profile)
    prof["classifications"] = [dict(c) for c in classes]
    prof["note"] = "Thermal activity attributed within the radius from loaded FIRMS history; not a compliance or risk rating."
    return {"events": [_with_display(dict(r)) for r in rows], "total": total, "limit": limit, "offset": offset,
            "weekly": [dict(r) for r in weekly], "profile": prof, "within_m": within_m}


@router.get("/facilities/{facility_id}/relationship", tags=["facilities"],
            summary="How one event relates to this facility: distance, and the attribution link if one was made")
def facility_relationship(facility_id: uuid.UUID, event: str = Query(..., max_length=64), user: User = CurrentUser,
                          db: Session = Depends(get_db)):
    from app.repositories import events as event_repo

    eid = event_repo.resolve_event_id(db, event)
    row = db.execute(text("""
        SELECT e.id, e.public_id, e.latitude, e.longitude, e.first_detected, e.last_detected, e.classification,
               e.confidence_state, e.confidence_score, e.frp_max,
               ST_Distance(e.geom, f.geom) AS distance_m, l.distance_m AS link_distance_m, l.bearing_deg, l.rank,
               l.attribution_score
        FROM thermal_events e JOIN facilities f ON f.id = :fid
        LEFT JOIN event_facility_links l ON l.event_id = e.id AND l.facility_id = f.id
        WHERE e.id = :eid"""), {"fid": facility_id, "eid": eid}).mappings().first()
    if row is None:
        raise NotFound("Facility not found")
    r = dict(row)
    distance = r["link_distance_m"] if r["link_distance_m"] is not None else r["distance_m"]
    evidence = [dict(x) for x in db.execute(text(
        """SELECT statement, direction, strength, knowledge_type FROM classification_evidence
           WHERE event_id = :eid AND category = 'facility' ORDER BY strength DESC LIMIT 6"""), {"eid": eid}).mappings()]
    temporal = db.execute(text("""
        SELECT count(DISTINCT e.id) FILTER (WHERE e.last_detected >= ev.first_detected - interval '30 days'
                                             AND e.first_detected <= ev.last_detected + interval '30 days') AS around_event,
               count(DISTINCT e.id) AS total, min(e.first_detected) AS first_activity, max(e.last_detected) AS last_activity
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id, (SELECT first_detected, last_detected FROM thermal_events WHERE id = :eid) ev
        WHERE l.facility_id = :fid AND l.distance_m <= 2000"""), {"eid": eid, "fid": facility_id}).mappings().one()
    return {
        "event": {k: r[k] for k in ("id", "public_id", "latitude", "longitude", "first_detected", "last_detected",
                                     "classification", "confidence_state", "confidence_score", "frp_max")},
        "linked": r["rank"] is not None, "distance_m": distance, "bearing_deg": r["bearing_deg"], "rank": r["rank"],
        "attribution_score": r["attribution_score"],
        "rule_radius_m": 2000, "search_radius_m": settings.attribution_radius_m,
        "evidence": evidence,
        "temporal": {**dict(temporal), "note": "Events within 2 km of the facility active within 30 days of this event's span."},
        "note": ("This facility is associated with the event based on spatial proximity and available facility-source "
                 "evidence. Facility attribution is supporting evidence, not proof of causation."),
    }


@router.get("/satellite/{observation_id}/swir.png", tags=["satellite"],
            summary="AOI SWIR composite (B12/B8A/B4) via Copernicus — requires CDSE OAuth credentials")
def swir(observation_id: uuid.UUID, user: User = AnalystUser, db: Session = Depends(get_db)):
    obs = db.get(SatelliteObservation, observation_id)
    if obs is None:
        raise NotFound("Satellite observation not found")
    if not SatellitePreviewService.swir_available():
        raise ProviderNotConfigured("SWIR rendering requires COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET")
    ev = db.execute(text("SELECT latitude, longitude FROM thermal_events WHERE id = :id"), {"id": obs.event_id}).one()
    t0 = time.perf_counter()
    try:
        png = SatellitePreviewService().render_swir(ev.latitude, ev.longitude, obs.acquired_at)
    except ProviderError as exc:
        category = source_health.error_category(exc)
        source_health.record_failure(db, "cdse", exc, category)
        source_health.record_check(db, "cdse", "preview", False, (time.perf_counter() - t0) * 1000, exc.status, category)
        db.commit()
        raise SourceUnavailable(f"Copernicus processing unavailable: {exc.kind}") from None
    source_health.record_success(db, "cdse", (time.perf_counter() - t0) * 1000)
    source_health.record_check(db, "cdse", "preview", True, (time.perf_counter() - t0) * 1000, 200)
    db.commit()
    return Response(png, media_type="image/png", headers={"cache-control": "private, max-age=86400"})


@router.get("/weather/current", tags=["weather"], summary="Current conditions at a point (live, not stored)")
def current_weather(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), user: User = CurrentUser,
                    db: Session = Depends(get_db)):
    from app.services import cache

    key = cache.make_key("weather_current", lat=round(lat, 2), lon=round(lon, 2))
    hit = cache.get(db, key)
    if hit is not None:
        return hit
    try:
        w = WeatherClient().current(lat, lon)
    except ProviderError as exc:
        raise SourceUnavailable(f"Weather source unavailable ({source_health.error_category(exc)})") from None
    out = {"observed_at": w.observed_at, "dataset": w.dataset, "temperature_c": w.temperature_c, "humidity_pct": w.humidity_pct,
            "wind_speed_ms": w.wind_speed_ms, "wind_direction_deg": w.wind_direction_deg,
            "dispersion_bearing_deg": w.dispersion_bearing_deg, "precipitation_mm": w.precipitation_mm,
            "pressure_hpa": w.pressure_hpa, "condition": w.condition, "source": "Open-Meteo"}
    cache.put(db, key, jsonable_encoder(out), timedelta(minutes=10))
    db.commit()
    return out


@router.get("/push/public-key", tags=["push"])
def push_key(user: User = CurrentUser):
    return {"configured": bool(settings.vapid_public_key and settings.vapid_private_key), "public_key": settings.vapid_public_key}


@router.post("/push/subscriptions", status_code=201, tags=["push"])
def push_subscribe(body: PushSubscriptionIn, request: Request, user: User = AnalystUser, db: Session = Depends(get_db)):
    if not body.endpoint.startswith("https://") or not {"p256dh", "auth"} <= body.keys.keys():
        raise AppError("Invalid push subscription", code="invalid_subscription")
    previous = db.execute(select(PushSubscription.user_id).where(PushSubscription.endpoint == body.endpoint)).scalar()
    audit.record(db, request, user.id, "push.subscribe", "push_subscription", None,
                 {"moved_from_other_user": bool(previous and previous != user.id)})
    stmt = insert(PushSubscription).values(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys["p256dh"], auth=body.keys["auth"])
    db.execute(stmt.on_conflict_do_update(index_elements=[PushSubscription.endpoint],
                                          set_={"user_id": user.id, "p256dh": body.keys["p256dh"], "auth": body.keys["auth"]}))
    db.commit()
    return {"subscribed": True}


@router.delete("/push/subscriptions", status_code=204, tags=["push"])
def push_unsubscribe(endpoint: str, request: Request, user: User = CurrentUser, db: Session = Depends(get_db)):
    sub = db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id)).scalar_one_or_none()
    if sub:
        audit.record(db, request, user.id, "push.unsubscribe", "push_subscription", sub.id)
        db.delete(sub)
        db.commit()

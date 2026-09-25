"""Facilities, satellite imagery, weather and push-subscription endpoints."""
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import AnalystUser, CurrentUser, Page, pagination
from app.core.errors import AppError, NotFound, ProviderNotConfigured, SourceUnavailable
from app.db.session import get_db
from app.gis.geo import bbox_from_string
from app.integrations.http import ProviderError
from app.integrations.sentinel import SatellitePreviewService
from app.integrations.weather import WeatherClient
from app.models.auth import PushSubscription, User
from app.models.enrichment import SatelliteObservation
from app.schemas.api import FacilityOut, PushSubscriptionIn
from app.schemas.api import Page as PageOut

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
        params["q"] = f"%{q}%"
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
def facilities_geojson(bbox: str = Query(...), facility_type: list[str] | None = Query(None), limit: int = Query(4000, le=10000),
                       user: User = CurrentUser, db: Session = Depends(get_db)):
    where, params = _fac_filters(bbox, facility_type, None, None)
    rows = db.execute(text(f"SELECT {_FAC_COLS} FROM facilities f WHERE {where} LIMIT :limit"), {**params, "limit": limit + 1}).mappings().all()
    return {"type": "FeatureCollection", "truncated": len(rows) > limit, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
         "properties": {"id": str(r["id"]), "name": r["name"], "type": r["facility_type"], "source": r["primary_source"],
                        "sources": r["source_count"], "confidence": r["confidence"]}} for r in rows[:limit]]}


@router.get("/facilities/{facility_id}", response_model=FacilityOut, tags=["facilities"])
def get_facility(facility_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    row = db.execute(text(f"""SELECT {_FAC_COLS},
        (SELECT count(*) FROM event_facility_links l WHERE l.facility_id = f.id AND l.distance_m <= 3000) AS event_count,
        (SELECT json_agg(json_build_object('source', s.source_id, 'external_id', s.external_id, 'name', s.name,
            'source_type', s.source_type, 'url', s.source_url, 'dataset_version', s.dataset_version,
            'published_at', s.published_at, 'retrieved_at', s.retrieved_at)) FROM facility_sources s WHERE s.facility_id = f.id) AS sources
        FROM facilities f WHERE f.id = :id"""), {"id": facility_id}).mappings().first()
    if row is None:
        raise NotFound("Facility not found")
    return dict(row)


@router.get("/facilities/{facility_id}/events", tags=["facilities"], summary="Facility-level thermal history")
def facility_events(facility_id: uuid.UUID, within_m: float = Query(3000, le=10000), user: User = CurrentUser,
                    db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT e.id, e.public_id, e.first_detected, e.last_detected, e.classification, e.persistence_class,
               e.confidence_state, e.review_status, e.observation_count, e.frp_max, l.distance_m
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w ORDER BY e.last_detected DESC LIMIT 200"""),
        {"id": facility_id, "w": within_m}).mappings().all()
    weekly = db.execute(text("""
        SELECT date_trunc('week', d.acq_datetime) AS week, count(*) AS detections, max(d.frp) AS frp_max
        FROM event_facility_links l JOIN thermal_detections d ON d.event_id = l.event_id
        WHERE l.facility_id = :id AND l.distance_m <= :w GROUP BY 1 ORDER BY 1"""), {"id": facility_id, "w": within_m}).mappings().all()
    return {"events": [dict(r) for r in rows], "weekly": [dict(r) for r in weekly]}


@router.get("/satellite/{observation_id}/swir.png", tags=["satellite"],
            summary="AOI SWIR composite (B12/B8A/B4) via Copernicus — requires CDSE OAuth credentials")
def swir(observation_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    obs = db.get(SatelliteObservation, observation_id)
    if obs is None:
        raise NotFound("Satellite observation not found")
    if not SatellitePreviewService.swir_available():
        raise ProviderNotConfigured("SWIR rendering requires COPERNICUS_CLIENT_ID and COPERNICUS_CLIENT_SECRET")
    ev = db.execute(text("SELECT latitude, longitude FROM thermal_events WHERE id = :id"), {"id": obs.event_id}).one()
    try:
        png = SatellitePreviewService().render_swir(ev.latitude, ev.longitude, obs.acquired_at)
    except ProviderError as exc:
        raise SourceUnavailable(f"Copernicus processing unavailable: {exc.kind}") from None
    return Response(png, media_type="image/png", headers={"cache-control": "private, max-age=86400"})


@router.get("/weather/current", tags=["weather"], summary="Current conditions at a point (live, not stored)")
def current_weather(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), user: User = CurrentUser):
    try:
        w = WeatherClient().current(lat, lon)
    except ProviderError as exc:
        raise SourceUnavailable(f"Weather source unavailable ({exc.kind})") from None
    return {"observed_at": w.observed_at, "dataset": w.dataset, "temperature_c": w.temperature_c, "humidity_pct": w.humidity_pct,
            "wind_speed_ms": w.wind_speed_ms, "wind_direction_deg": w.wind_direction_deg,
            "dispersion_bearing_deg": w.dispersion_bearing_deg, "precipitation_mm": w.precipitation_mm,
            "pressure_hpa": w.pressure_hpa, "condition": w.condition, "source": "Open-Meteo"}


@router.get("/push/public-key", tags=["push"])
def push_key(user: User = CurrentUser):
    return {"configured": bool(settings.vapid_public_key and settings.vapid_private_key), "public_key": settings.vapid_public_key}


@router.post("/push/subscriptions", status_code=201, tags=["push"])
def push_subscribe(body: PushSubscriptionIn, user: User = AnalystUser, db: Session = Depends(get_db)):
    if not body.endpoint.startswith("https://") or not {"p256dh", "auth"} <= body.keys.keys():
        raise AppError("Invalid push subscription", code="invalid_subscription")
    stmt = insert(PushSubscription).values(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys["p256dh"], auth=body.keys["auth"])
    db.execute(stmt.on_conflict_do_update(index_elements=[PushSubscription.endpoint],
                                          set_={"user_id": user.id, "p256dh": body.keys["p256dh"], "auth": body.keys["auth"]}))
    db.commit()
    return {"subscribed": True}


@router.delete("/push/subscriptions", status_code=204, tags=["push"])
def push_unsubscribe(endpoint: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    sub = db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id)).scalar_one_or_none()
    if sub:
        db.delete(sub)
        db.commit()

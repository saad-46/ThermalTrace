"""Event enrichment: OSM infrastructure + land use, ESA WorldCover land cover, weather, Sentinel-2 scenes, admin geocoding.

Each step records its own status in event.enrichment_state[step] = {status, at, detail, ...}:
`ok` (the provider answered; for imagery that may be zero scenes), `no_data` (the provider answered
without an observation for that time and place) or `failed` (the provider could not be reached or
refused). A failed provider never inserts substitute values.
"""
import logging
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.gis.geo import haversine_m
from app.integrations.http import ProviderError, request
from app.integrations.overpass import OsmFeature, OverpassClient, classify_land
from app.integrations.sentinel import SatelliteSearchService
from app.integrations.weather import WeatherClient, WeatherNoData
from app.models.enrichment import SatelliteObservation, WeatherObservation
from app.models.facilities import LandContext
from app.models.thermal import ThermalEvent
from app.services import cache, facility_sync, landcover, source_health

logger = logging.getLogger(__name__)
CELL_DEG = 0.05  # ≈5.5 km; one Overpass request serves every event in a cell
LAND_RADIUS_M = 1500
MAX_LAND_POINTS = 12
STEPS = ("osm", "landcover", "weather", "satellite", "geocode")
SATELLITE_LOOKBACK_DAYS = 45
SATELLITE_AFTER_DAYS = 60


def _mark(ev: ThermalEvent, step: str, status: str, detail: str | None = None, **extra) -> None:
    state = dict(ev.enrichment_state or {})
    state[step] = {"status": status, "at": datetime.now(UTC).isoformat(), "detail": detail, **extra}
    ev.enrichment_state = state
    flag_modified(ev, "enrichment_state")


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG))


def _point_bounds_distance(lat: float, lon: float, f) -> float:
    """0 if the event lies inside the feature's bounding box, else distance to its centre."""
    b = f.bounds
    if b and b["minlat"] <= lat <= b["maxlat"] and b["minlon"] <= lon <= b["maxlon"]:
        return 0.0
    return haversine_m(lat, lon, f.latitude, f.longitude)


def enrich_osm(db: Session, events: list[ThermalEvent]) -> dict:
    """Group events by cell; one Overpass request per cell.

    Cells whose surroundings are covered by the local facility index (facility_sync) only query
    land use — a small, fast request. Other cells fall back to the bounded facility+land query."""
    client = OverpassClient()
    by_cell: dict[tuple[int, int], list[ThermalEvent]] = defaultdict(list)
    for ev in events:
        by_cell[_cell(ev.latitude, ev.longitude)].append(ev)
    stats = {"cells": 0, "cached": 0, "failed": 0, "facilities_new": 0, "land_only": 0}
    for (cy, cx), cell_events in by_cell.items():
        clat, clon = (cy + 0.5) * CELL_DEG, (cx + 0.5) * CELL_DEG
        points = [(e.latitude, e.longitude) for e in cell_events[:MAX_LAND_POINTS]]
        fac_radius = int(settings.attribution_radius_m + 4000)
        needed = set().union(*(facility_sync.tiles_around(e.latitude, e.longitude) for e in cell_events))
        land_only = facility_sync.fresh_tiles(db, needed) == needed
        key = cache.make_key("overpass-land" if land_only else "overpass", cell=(cy, cx), r=fac_radius,
                             pts=[(round(a, 3), round(b, 3)) for a, b in points])
        cached = cache.get(db, key)
        db.commit()  # release the snapshot before a slow provider call (no idle-in-transaction sessions)
        if cached:
            stats["cached"] += 1

            feats = [OsmFeature(**f) for f in cached["features"]]
            endpoint = cached["endpoint"]
        else:
            try:
                if land_only:
                    feats, endpoint, latency = client.query_land(points, LAND_RADIUS_M)
                else:
                    feats, endpoint, latency = client.query_around(clat, clon, fac_radius, LAND_RADIUS_M, land_points=points)
            except ProviderError as exc:
                stats["failed"] += 1
                source_health.record_failure(db, "osm", str(exc))
                for ev in cell_events:
                    _mark(ev, "osm", "failed", f"{exc.kind}: {exc}")
                db.commit()
                continue
            source_health.record_success(db, "osm", latency, len(feats))
            cache.put(db, key, {"endpoint": endpoint, "features": [f.__dict__ for f in feats]},
                      timedelta(hours=settings.osm_cache_ttl_hours))
        stats["cells"] += 1
        stats["land_only"] += int(land_only)
        retrieved = datetime.now(UTC)
        if not land_only:
            stats["facilities_new"] += facility_sync.upsert_osm_facilities(db, feats, endpoint)
        for ev in cell_events:
            db.execute(delete(LandContext).where(LandContext.event_id == ev.id))
            for f in feats:
                cat = classify_land(f.tags)
                if not cat:
                    continue
                d = _point_bounds_distance(ev.latitude, ev.longitude, f)
                if d > LAND_RADIUS_M + 500:
                    continue
                db.execute(insert(LandContext).values(
                    event_id=ev.id, osm_type=f.osm_type, osm_id=f.osm_id, category=cat, name=f.name,
                    distance_m=round(d, 1), tags=f.tags, retrieved_at=retrieved).on_conflict_do_nothing())
            source = "local facility index + OSM land use" if land_only else "OSM facilities + land use"
            _mark(ev, "osm", "ok", f"{source} via {endpoint.split('/')[2]} ({len(feats)} features)")
        db.commit()
    return stats


def enrich_weather(db: Session, ev: ThermalEvent) -> None:
    try:
        w = WeatherClient().conditions_at(ev.latitude, ev.longitude, ev.last_detected)
    except WeatherNoData as exc:  # the provider answered: no observation for this hour and place
        source_health.record_success(db, "open_meteo", exc.latency_ms, 0)
        _mark(ev, "weather", "no_data", str(exc), requested_at=ev.last_detected.isoformat())
        return
    except ProviderError as exc:
        logger.warning("weather lookup failed for %s: %s", ev.public_id, exc)
        source_health.record_failure(db, "open_meteo", str(exc))
        _mark(ev, "weather", "failed", f"{exc.kind}: {exc}", category=source_health.error_category(exc))
        return
    source_health.record_success(db, "open_meteo", w.latency_ms, 1, w.observed_at)
    stmt = insert(WeatherObservation).values(
        event_id=ev.id, kind="at_last_detection", source_id="open_meteo", dataset=w.dataset, observed_at=w.observed_at,
        retrieved_at=datetime.now(UTC), latitude=ev.latitude, longitude=ev.longitude,
        temperature_c=w.temperature_c, humidity_pct=w.humidity_pct, wind_speed_ms=w.wind_speed_ms,
        wind_direction_deg=w.wind_direction_deg, precipitation_mm=w.precipitation_mm, pressure_hpa=w.pressure_hpa,
        weather_code=w.weather_code, condition=w.condition, raw=w.raw,
    )
    db.execute(stmt.on_conflict_do_nothing(constraint="uq_weather_event_kind_time"))
    _mark(ev, "weather", "ok", w.dataset, requested_at=ev.last_detected.isoformat())


def enrich_satellite(db: Session, ev: ThermalEvent) -> None:
    """Sentinel-2 L2A scenes whose footprint contains the event, under the cloud threshold, in two windows: the
    newest scenes in the 45 days before the first detection, and the oldest from the first detection onward (up to
    60 days after the last). A single newest-first search would, for an older event, return only recent scenes and
    never the ones before it. The step records how many scenes fall before and after the event, which is what the
    NDVI/NBR comparison needs."""
    now = datetime.now(UTC)
    start = ev.first_detected - timedelta(days=SATELLITE_LOOKBACK_DAYS)
    end = min(now, ev.last_detected + timedelta(days=SATELLITE_AFTER_DAYS))
    window = {"window_start": start.isoformat(), "window_end": end.isoformat(), "max_cloud": settings.satellite_max_cloud}
    svc = SatelliteSearchService()
    try:
        prior, lat_a = svc.search(ev.latitude, ev.longitude, start, ev.first_detected, limit=8, newest_first=True)
        since, lat_b = svc.search(ev.latitude, ev.longitude, ev.first_detected, end, limit=20, newest_first=False)
        unique = {s.item_id: s for s in prior + since}  # the windows share only their boundary
        scenes = sorted(unique.values(), key=lambda s: s.acquired_at, reverse=True)
        latency = (lat_a + lat_b) / 2
    except ProviderError as exc:
        logger.warning("Sentinel-2 search failed for %s: %s", ev.public_id, exc)
        source_health.record_failure(db, "earth_search", str(exc))
        _mark(ev, "satellite", "failed", f"{exc.kind}: {exc}", category=source_health.error_category(exc), **window)
        return
    source_health.record_success(db, "earth_search", latency, len(scenes), scenes[0].acquired_at if scenes else None)
    before = [s for s in scenes if s.acquired_at < ev.first_detected][:4]  # nearest first
    during = [s for s in scenes if ev.first_detected <= s.acquired_at <= ev.last_detected + timedelta(hours=12)][-4:]
    after = sorted((s for s in scenes if s.acquired_at > ev.last_detected + timedelta(hours=12)), key=lambda s: s.acquired_at)[:3]
    keep = [(s, "before") for s in before] + [(s, "during") for s in during] + [(s, "after") for s in after]
    db.execute(delete(SatelliteObservation).where(SatelliteObservation.event_id == ev.id))
    now = datetime.now(UTC)
    for s, rel in keep:
        db.add(SatelliteObservation(
            event_id=ev.id, provider=s.provider, source_id=s.source_id, collection=s.collection, item_id=s.item_id,
            platform=s.platform, acquired_at=s.acquired_at, cloud_cover=s.cloud_cover, processing_level=s.processing_level,
            relation=rel, thumbnail_url=s.thumbnail_url, item_url=s.item_url, bbox=s.bbox, assets=s.assets, retrieved_at=now,
        ))
    _mark(ev, "satellite", "ok", f"{len(keep)} scene(s) ≤{settings.satellite_max_cloud:.0f}% cloud",
          scenes=len(keep), before=len(before), after=len(after), **window)


def enrich_geocode(db: Session, ev: ThermalEvent) -> None:
    key = cache.make_key("nominatim", lat=round(ev.latitude, 2), lon=round(ev.longitude, 2))
    data = cache.get(db, key)
    if data is None:
        try:
            res = request("nominatim", "GET", f"{settings.nominatim_url}/reverse",
                          params={"lat": ev.latitude, "lon": ev.longitude, "format": "jsonv2", "zoom": 10,
                                  "accept-language": "en"}, timeout=15, max_attempts=2, min_interval_s=1.1)
            data = res.response.json()
        except (ProviderError, ValueError) as exc:
            source_health.record_failure(db, "nominatim", str(exc))
            _mark(ev, "geocode", "failed", str(exc))
            return
        source_health.record_success(db, "nominatim", res.latency_ms, 1)
        cache.put(db, key, data, timedelta(days=90))
    addr = data.get("address") or {}
    if not addr:
        ev.country = "Offshore / unaddressed"
        _mark(ev, "geocode", "ok", "no address (likely offshore)")
        return
    ev.country = addr.get("country")
    ev.admin_state = addr.get("state") or addr.get("region")
    ev.admin_district = addr.get("state_district") or addr.get("county") or addr.get("city")
    _mark(ev, "geocode", "ok", "OSM Nominatim")


def enrich_events(db: Session, event_ids: list, steps: tuple[str, ...] = STEPS) -> dict:
    from app.processing.persistence import history_window_days
    from app.processing.pipeline import analyse_event

    events = list(db.execute(select(ThermalEvent).where(ThermalEvent.id.in_(event_ids))).scalars())
    out: dict = {"events": len(events)}
    if "osm" in steps:
        out["osm"] = enrich_osm(db, events)
    for ev in events:
        if "landcover" in steps:
            landcover.enrich_landcover(db, ev, _mark)
        if "weather" in steps:
            enrich_weather(db, ev)
        if "satellite" in steps:
            enrich_satellite(db, ev)
        if "geocode" in steps:
            enrich_geocode(db, ev)
        db.commit()
    window = history_window_days(db)
    for ev in events:
        with db.begin_nested():
            analyse_event(db, ev.id, window)
    db.commit()
    return out


def enrichment_priority(db: Session, limit: int) -> list:
    """Events most worth enriching first: not yet enriched, multi-observation / high FRP / recent."""
    return list(db.execute(text(
        """SELECT id FROM thermal_events
           WHERE NOT (enrichment_state ? 'osm') OR enrichment_state->'osm'->>'status' <> 'ok'
           ORDER BY (observation_count >= 3) DESC, observation_count DESC, frp_max DESC NULLS LAST, last_detected DESC
           LIMIT :n"""), {"n": limit}).scalars())


def landcover_backfill_ids(db: Session, limit: int) -> list:
    """Events that have not had a land-cover lookup yet, most review-worthy first (triage priority)."""
    return list(db.execute(text(
        """SELECT id FROM thermal_events
           WHERE NOT (enrichment_state ? 'landcover')
           ORDER BY priority_score DESC NULLS LAST, last_detected DESC
           LIMIT :n"""), {"n": limit}).scalars())


def context_backfill_ids(db: Session, limit: int) -> list:
    """Events inside India without weather or Sentinel-2 context, most review-worthy first (triage priority).
    Both lookups are single requests (~1 s), unlike the Overpass step that paces full enrichment."""
    return list(db.execute(text(
        """SELECT id FROM thermal_events
           WHERE in_india IS NOT FALSE AND data_mode <> 'demo'
             AND (NOT (enrichment_state ? 'weather') OR NOT (enrichment_state ? 'satellite'))
           ORDER BY priority_score DESC NULLS LAST, last_detected DESC
           LIMIT :n"""), {"n": limit}).scalars())

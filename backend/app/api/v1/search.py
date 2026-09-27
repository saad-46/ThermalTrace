"""Global search (header search bar on desktop and mobile).

Accepts an event public id, place (district / state), facility name or operator, a
classification word, or coordinates ("21.10, 72.64" or "21.10 72.64"). Server-side and
trigram-indexed, so it scales with the dataset instead of filtering in the browser.
"""
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser
from app.db import like as like_pattern
from app.db.session import get_db
from app.ml.base import CLASS_LABELS
from app.models.auth import User

router = APIRouter(tags=["search"])
_ID_PREFIX = re.compile(r"^TT-\d{4}(-\d{0,6})?$")
_COORD = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_coordinates(q: str) -> tuple[float, float] | None:
    m = _COORD.match(q)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


@router.get("/search", summary="Search events, places, facilities, classifications and coordinates")
def search(q: str = Query(min_length=2, max_length=100), user: User = CurrentUser, db: Session = Depends(get_db)):
    out: dict = {"query": q, "coordinates": None, "events": [], "places": [], "states": [], "facilities": [], "classifications": []}
    coords = parse_coordinates(q)
    if coords:
        lat, lon = coords
        out["coordinates"] = {"latitude": lat, "longitude": lon}
        out["events"] = [dict(r) for r in db.execute(text(
            """SELECT id, public_id, classification, confidence_state, review_status, admin_district, admin_state,
                      place_name, place_admin1, place_country,
                      round(ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)) AS distance_m
               FROM thermal_events
               WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 25000) AND in_india IS NOT FALSE
               ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography LIMIT 8"""),
            {"lat": lat, "lon": lon}).mappings()]
        return out

    if len(re.sub(r"[\W_]+", "", q)) < 2:
        # nothing searchable (punctuation, wildcards): matches no name, and would defeat the trigram indexes
        return out
    like = like_pattern.contains(q)
    cols = """id, public_id, classification, confidence_state, review_status, admin_district, admin_state,
              place_name, place_admin1, place_country, NULL AS distance_m"""
    prefix = q.strip().upper()
    if _ID_PREFIX.match(prefix):
        # an event-id prefix ("TT-2026-10"): a range on the unique btree index instead of a trigram match over
        # tens of thousands of ids
        hi = prefix[:-1] + chr(ord(prefix[-1]) + 1)
        rows = db.execute(text(f"SELECT {cols} FROM thermal_events WHERE public_id >= :lo AND public_id < :hi "
                               "ORDER BY public_id DESC LIMIT 6"), {"lo": prefix, "hi": hi}).mappings()
    else:
        rows = db.execute(text(f"SELECT {cols} FROM thermal_events WHERE public_id ILIKE :like ORDER BY last_detected DESC LIMIT 6"),
                          {"like": like}).mappings()
    out["events"] = [dict(r) for r in rows]
    out["places"] = [dict(r) for r in db.execute(text(
        """SELECT coalesce(admin_district, place_name) AS admin_district, coalesce(admin_state, place_admin1) AS admin_state,
                  count(*) AS events, avg(latitude) AS latitude, avg(longitude) AS longitude
             FROM thermal_events
            WHERE (admin_district ILIKE :like OR admin_state ILIKE :like OR place_name ILIKE :like) AND in_india IS NOT FALSE
           GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT 6"""), {"like": like}).mappings()]
    # facilities by name or operator, then by a registry identifier (GEM / WRI / OSM id, CEA station): all trigram-indexed
    out["facilities"] = [dict(r) for r in db.execute(text(
        """SELECT id, name, facility_type, operator, latitude, longitude, primary_source, match, matched_value FROM (
             SELECT f.id, f.name, f.facility_type, f.operator, f.latitude, f.longitude, f.primary_source, f.source_count,
                    CASE WHEN f.name ILIKE :like THEN 'name' ELSE 'operator' END AS match, NULL::text AS matched_value, 0 AS o
             FROM facilities f WHERE f.name ILIKE :like OR f.operator ILIKE :like
             UNION ALL
             SELECT f.id, f.name, f.facility_type, f.operator, f.latitude, f.longitude, f.primary_source, f.source_count,
                    'registry id' AS match, s.source_id || ': ' || s.external_id AS matched_value, 1 AS o
             FROM facility_sources s JOIN facilities f ON f.id = s.facility_id WHERE s.external_id ILIKE :like
             UNION ALL
             SELECT f.id, f.name, f.facility_type, f.operator, f.latitude, f.longitude, f.primary_source, f.source_count,
                    'registry station' AS match, upper(r.source_id) || ': ' || r.name AS matched_value, 2 AS o
             FROM registry_stations r JOIN facilities f ON f.id = r.facility_id WHERE r.name ILIKE :like
           ) x ORDER BY o, source_count DESC, name LIMIT 8"""), {"like": like}).mappings()]
    seen: set = set()
    out["facilities"] = [r for r in out["facilities"] if not (r["id"] in seen or seen.add(r["id"]))][:6]
    out["states"] = [dict(r) for r in db.execute(text(
        """SELECT COALESCE(admin_state, place_admin1) AS state, count(*) AS events, avg(latitude) AS latitude, avg(longitude) AS longitude
           FROM thermal_events WHERE (admin_state ILIKE :like OR place_admin1 ILIKE :like) AND in_india IS NOT FALSE
           GROUP BY 1 ORDER BY 2 DESC LIMIT 3"""), {"like": like}).mappings()]
    ql = q.strip().lower()
    out["classifications"] = [{"key": k, "label": v} for k, v in CLASS_LABELS.items()
                              if ql in v.lower() or ql in k.replace("_", " ")]
    return out

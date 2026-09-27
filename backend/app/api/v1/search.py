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
from app.db.session import get_db
from app.ml.base import CLASS_LABELS
from app.models.auth import User

router = APIRouter(tags=["search"])
_COORD = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def parse_coordinates(q: str) -> tuple[float, float] | None:
    m = _COORD.match(q)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


@router.get("/search", summary="Search events, places, facilities, classifications and coordinates")
def search(q: str = Query(min_length=2, max_length=100), user: User = CurrentUser, db: Session = Depends(get_db)):
    out: dict = {"query": q, "coordinates": None, "events": [], "places": [], "facilities": [], "classifications": []}
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

    like = f"%{q.strip()}%"
    out["events"] = [dict(r) for r in db.execute(text(
        """SELECT id, public_id, classification, confidence_state, review_status, admin_district, admin_state,
                  place_name, place_admin1, place_country, NULL AS distance_m
           FROM thermal_events WHERE public_id ILIKE :like
           ORDER BY last_detected DESC LIMIT 6"""), {"like": like}).mappings()]
    out["places"] = [dict(r) for r in db.execute(text(
        """SELECT coalesce(admin_district, place_name) AS admin_district, coalesce(admin_state, place_admin1) AS admin_state,
                  count(*) AS events, avg(latitude) AS latitude, avg(longitude) AS longitude
             FROM thermal_events
            WHERE (admin_district ILIKE :like OR admin_state ILIKE :like OR place_name ILIKE :like) AND in_india IS NOT FALSE
           GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT 6"""), {"like": like}).mappings()]
    out["facilities"] = [dict(r) for r in db.execute(text(
        """SELECT id, name, facility_type, operator, latitude, longitude, primary_source
           FROM facilities WHERE name ILIKE :like OR operator ILIKE :like
           ORDER BY source_count DESC, name LIMIT 6"""), {"like": like}).mappings()]
    ql = q.strip().lower()
    out["classifications"] = [{"key": k, "label": v} for k, v in CLASS_LABELS.items()
                              if ql in v.lower() or ql in k.replace("_", " ")]
    return out

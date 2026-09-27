"""Offline place names for events: the nearest populated place from GeoNames (cities500, CC BY 4.0).

The online geocoder (Nominatim) is limited to about one request per second, so it cannot name hundreds of
thousands of events. This gives every event a "near <place>, <state>" label from a local PostGIS table
in one query. It is a nearest-populated-place label, not an administrative boundary lookup: the wording
in the UI is always "near", with the distance, and an event more than MAX_DISTANCE_M from any place stays
unnamed rather than getting a misleading one.
"""
import csv
import io
import logging
import time
import zipfile

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.http import ProviderError, request
from app.models.places import Place
from app.services import source_health

logger = logging.getLogger(__name__)
SOURCE_ID = "geonames"
CITIES_URL = "https://download.geonames.org/export/dump/cities500.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
MAX_DISTANCE_M = 50_000
REGION_PAD_DEG = 3.0  # keep places slightly outside the region of interest so border events still find a neighbour


def parse_admin1(text_: str) -> dict[str, str]:
    """admin1CodesASCII.txt: `IN.36<TAB>Jharkhand<TAB>Jharkhand<TAB>id` -> {"IN.36": "Jharkhand"}."""
    out: dict[str, str] = {}
    for line in text_.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and "." in parts[0]:
            out[parts[0]] = parts[1]
    return out


def parse_cities(tsv: str, admin1: dict[str, str], bbox: tuple[float, float, float, float], pad: float = REGION_PAD_DEG) -> list[dict]:
    """GeoNames dump columns: 0 id, 1 name, 4 lat, 5 lon, 8 country code, 10 admin1 code, 14 population."""
    west, south, east, north = bbox
    rows = []
    for r in csv.reader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(r) < 15:
            continue
        try:
            lat, lon = float(r[4]), float(r[5])
        except ValueError:
            continue
        if not (west - pad <= lon <= east + pad and south - pad <= lat <= north + pad):
            continue
        rows.append({"geonameid": int(r[0]), "name": r[1], "admin1": admin1.get(f"{r[8]}.{r[10]}"), "country_code": r[8],
                     "population": int(r[14] or 0), "latitude": lat, "longitude": lon})
    return rows


def import_places(db: Session) -> dict:
    """Download GeoNames and load the places inside (region of interest + padding). Safe to re-run."""
    started = time.perf_counter()
    try:
        zbytes = request("geonames", "GET", CITIES_URL, timeout=120, max_attempts=3).response.content
        admin_txt = request("geonames", "GET", ADMIN1_URL, timeout=60, max_attempts=3).response.text
    except ProviderError as exc:
        source_health.record_failure(db, SOURCE_ID, exc)
        db.commit()
        raise
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        tsv = z.read("cities500.txt").decode("utf-8")
    rows = parse_cities(tsv, parse_admin1(admin_txt), settings.region_bbox)
    db.execute(text("DELETE FROM places"))
    for i in range(0, len(rows), 5000):
        db.execute(Place.__table__.insert(), [
            {**{k: r[k] for k in ("geonameid", "name", "admin1", "country_code", "population", "latitude", "longitude")},
             "geom": f"SRID=4326;POINT({r['longitude']} {r['latitude']})"} for r in rows[i:i + 5000]])
    source_health.record_success(db, SOURCE_ID, (time.perf_counter() - started) * 1000, len(rows))
    db.commit()
    return {"places": len(rows), "source": "GeoNames cities500 (CC BY 4.0)"}


_ASSIGN = text(
    """
    UPDATE thermal_events e
       SET place_name = x.name, place_admin1 = x.admin1, place_country = x.country_code, place_distance_m = x.dist
      FROM (
        SELECT t.id, p.name, p.admin1, p.country_code, ST_Distance(p.geom, t.geom) AS dist
          FROM (SELECT id, geom FROM thermal_events WHERE place_name IS NULL AND place_distance_m IS NULL
                 AND (CAST(:ids AS uuid[]) IS NULL OR id = ANY(CAST(:ids AS uuid[])))
                 ORDER BY id LIMIT :lim) t
         CROSS JOIN LATERAL (SELECT name, admin1, country_code, geom FROM places
                              ORDER BY geom <-> t.geom LIMIT 1) p
      ) x
     WHERE e.id = x.id
    """
)
_MARK_FAR = text("UPDATE thermal_events SET place_name = NULL WHERE place_distance_m > :max")


def assign_nearest_places(db: Session, event_ids: list | None = None, batch: int = 20_000) -> int:
    """Name events by their nearest place. With `event_ids` only those events; otherwise every unnamed event,
    in batches. Events farther than MAX_DISTANCE_M keep their distance but no name (shown as coordinates)."""
    if not db.execute(text("SELECT EXISTS (SELECT 1 FROM places)")).scalar():
        return 0
    total = 0
    ids = [str(i) for i in event_ids] if event_ids is not None else None
    while True:
        n = db.execute(_ASSIGN, {"ids": ids, "lim": batch}).rowcount
        db.execute(_MARK_FAR, {"max": MAX_DISTANCE_M})
        db.commit()
        total += n
        if n < batch or ids is not None:
            return total

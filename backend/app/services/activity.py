"""Observed activity patterns: event clusters around an event, recurring activity at a place or facility, and facility
activity profiles. Counts of FIRMS-derived events and detections, never a risk rating.

All queries are bounded: spatial ones use the GiST index on thermal_events.geom (ST_DWithin), facility ones use
event_facility_links(facility_id), and result lists are limited. Windows are relative to now unless stated.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound

WEEK = 7
NOTE = ("Observed activity from satellite detections (FIRMS). It describes how often heat was seen, not a risk, and it "
        "does not establish what caused the heat.")
FRP_BINS = (0, 5, 10, 25, 50, 100, 250, 1_000_000)
BRIGHT_BINS = (300, 320, 340, 360, 380, 400, 450, 10_000)


def _hist(values: list[float], bins: tuple) -> list[dict]:
    out = []
    for lo, hi in zip(bins, bins[1:], strict=False):
        out.append({"from": lo, "to": None if hi >= 10_000 else hi, "n": sum(1 for v in values if v is not None and lo <= v < hi)})
    return out


def _dist(rows, key: str = "k") -> list[dict]:
    return [{"key": r[key] or "unclassified", "n": r["n"]} for r in rows]


# ---------------------------------------------------------------- cluster around an event
def cluster(db: Session, event_id: uuid.UUID, radius_km: float, days: int, limit: int = 200) -> dict:
    """Events within `radius_km` of the event and active within `days` of its span: the local cluster of activity."""
    anchor = db.execute(text("SELECT public_id, latitude, longitude, first_detected, last_detected FROM thermal_events WHERE id = :id"),
                        {"id": event_id}).mappings().first()
    if anchor is None:
        raise NotFound("Event not found")
    p = {"id": event_id, "r": radius_km * 1000.0, "d": days, "limit": limit}
    where = """ST_DWithin(e.geom, a.geom, :r) AND e.in_india IS NOT FALSE
               AND e.last_detected >= a.first_detected - make_interval(days => :d)
               AND e.first_detected <= a.last_detected + make_interval(days => :d)"""
    base = f"FROM thermal_events e, (SELECT geom, first_detected, last_detected FROM thermal_events WHERE id = :id) a WHERE {where}"
    agg = db.execute(text(f"""
        SELECT count(*) AS events, COALESCE(sum(e.observation_count), 0) AS detections, min(e.first_detected) AS first_detected,
               max(e.last_detected) AS last_detected, max(e.frp_max) AS frp_max, avg(e.frp_mean) AS frp_mean,
               ST_AsGeoJSON(ST_ConvexHull(ST_Collect(e.geom::geometry)))::json AS extent,
               max(ST_Distance(e.geom, a.geom)) AS max_distance_m
        {base}"""), p).mappings().one()
    classes = db.execute(text(f"SELECT e.classification AS k, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC"), p).mappings().all()
    persistence = db.execute(text(f"SELECT e.persistence_class AS k, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC"), p).mappings().all()
    landcover = db.execute(text(f"""
        SELECT lc.dominant AS k, count(*) AS n
        FROM thermal_events e CROSS JOIN (SELECT geom, first_detected, last_detected FROM thermal_events WHERE id = :id) a
        JOIN landcover_observations lc ON lc.event_id = e.id
        WHERE {where} GROUP BY 1 ORDER BY 2 DESC"""), p).mappings().all()
    facilities = db.execute(text(f"""
        SELECT f.id, f.name, f.facility_type, f.latitude, f.longitude, count(DISTINCT l.event_id) AS events,
               min(l.distance_m) AS min_distance_m, count(DISTINCT l.event_id) FILTER (WHERE l.rank = 1) AS attributed
        FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
        WHERE l.event_id IN (SELECT e.id {base}) AND l.distance_m <= 3000
        GROUP BY f.id ORDER BY events DESC, min_distance_m LIMIT 10"""), p).mappings().all()
    events = db.execute(text(f"""
        SELECT e.id, e.public_id, e.latitude, e.longitude, e.first_detected, e.last_detected, e.observation_count, e.frp_max,
               e.classification, e.persistence_class, e.confidence_state, e.review_status, e.priority_score,
               round(ST_Distance(e.geom, a.geom)) AS distance_m
        {base} ORDER BY e.first_detected LIMIT :limit"""), p).mappings().all()
    a = dict(agg)
    duration_h = ((a["last_detected"] - a["first_detected"]).total_seconds() / 3600) if a["events"] else 0
    return {
        "cluster_id": f"{anchor['public_id']}~{radius_km:g}km~{days}d", "anchor": dict(anchor), "radius_km": radius_km,
        "days": days, "summary": {**a, "duration_hours": round(duration_h, 1)},
        "classifications": _dist(classes), "persistence": _dist(persistence), "landcover": _dist(landcover),
        "facilities": [dict(r) for r in facilities], "events": [dict(r) for r in events], "truncated": a["events"] > limit,
        "note": ("An observed spatial / temporal grouping: events within the radius and active within the time window of this "
                 "event. It groups nearby "
                 "activity for review; it does not mean the events share a source or cause. " + NOTE),
    }


# ---------------------------------------------------------------- recurring activity
def _windows(now: datetime) -> dict:
    return {"now": now, "w1": now - timedelta(days=WEEK), "w2": now - timedelta(days=2 * WEEK),
            "m1": now - timedelta(days=30), "m2": now - timedelta(days=60)}


_COUNTS = """
    count(*) FILTER (WHERE e.last_detected >= :w1) AS this_week,
    count(*) FILTER (WHERE e.last_detected >= :w2 AND e.last_detected < :w1) AS previous_week,
    count(*) FILTER (WHERE e.last_detected >= :m1) AS last_30_days,
    count(*) FILTER (WHERE e.last_detected >= :m2 AND e.last_detected < :m1) AS previous_30_days,
    count(*) AS total, min(e.first_detected) AS first_activity, max(e.last_detected) AS last_activity,
    COALESCE(sum(e.observation_count), 0) AS detections, avg(e.frp_max) AS frp_max_mean, max(e.frp_max) AS frp_max
"""


def _summarise(row: dict, now: datetime) -> dict:
    r = dict(row)
    weeks = max(((now - r["first_activity"]).days / 7.0) if r.get("first_activity") else 0, 1.0)
    r["weekly_average"] = round(r["total"] / weeks, 2) if r["total"] else 0.0
    r["history_weeks"] = round(weeks, 1)
    return r


def recurrence_at(db: Session, event_id: uuid.UUID, radius_km: float) -> dict:
    """Recurring activity around an event's location (any event within the radius, whole loaded history)."""
    now = datetime.now(UTC)
    p = {"id": event_id, "r": radius_km * 1000.0, **_windows(now)}
    base = """FROM thermal_events e, (SELECT geom FROM thermal_events WHERE id = :id) a
              WHERE ST_DWithin(e.geom, a.geom, :r) AND e.in_india IS NOT FALSE"""
    row = db.execute(text(f"SELECT {_COUNTS} {base}"), p).mappings().one()
    classes = db.execute(text(f"SELECT e.classification AS k, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC"), p).mappings().all()
    pers = db.execute(text(f"SELECT e.persistence_class AS k, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC"), p).mappings().all()
    monthly = db.execute(text(f"""SELECT date_trunc('month', e.last_detected) AS month, count(*) AS events {base}
                                  GROUP BY 1 ORDER BY 1"""), p).mappings().all()
    return {"radius_km": radius_km, "activity": _summarise(row, now), "classifications": _dist(classes),
            "persistence": _dist(pers), "monthly": [dict(m) for m in monthly], "note": NOTE}


def recurring(db: Session, days: int, min_events: int, limit: int = 25) -> dict:
    """Facilities and places with repeated observed activity in the last `days`, with the previous period alongside."""
    now = datetime.now(UTC)
    p = {"since": now - timedelta(days=days), "prev": now - timedelta(days=2 * days), "min": min_events, "limit": limit}
    facilities = db.execute(text("""
        SELECT f.id, f.name, f.facility_type, f.latitude, f.longitude, f.state,
               count(DISTINCT e.id) FILTER (WHERE e.last_detected >= :since) AS current,
               count(DISTINCT e.id) FILTER (WHERE e.last_detected >= :prev AND e.last_detected < :since) AS previous,
               max(e.frp_max) AS frp_max, max(e.last_detected) AS last_activity
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id JOIN facilities f ON f.id = l.facility_id
        WHERE l.distance_m <= 2000 AND e.last_detected >= :prev AND e.in_india IS NOT FALSE
        GROUP BY f.id HAVING count(DISTINCT e.id) FILTER (WHERE e.last_detected >= :since) >= :min
        ORDER BY current DESC, previous LIMIT :limit"""), p).mappings().all()
    # places without a mapped facility within 2 km: ~5.5 km grid cells
    places = db.execute(text("""
        SELECT round(e.latitude / 0.05) * 0.05 AS latitude, round(e.longitude / 0.05) * 0.05 AS longitude,
               mode() WITHIN GROUP (ORDER BY coalesce(e.place_name, e.admin_district)) AS place,
               mode() WITHIN GROUP (ORDER BY coalesce(e.admin_state, e.place_admin1)) AS state,
               count(*) FILTER (WHERE e.last_detected >= :since) AS current,
               count(*) FILTER (WHERE e.last_detected < :since) AS previous, max(e.frp_max) AS frp_max,
               mode() WITHIN GROUP (ORDER BY e.classification) AS classification
        FROM thermal_events e
        WHERE e.last_detected >= :prev AND e.in_india IS NOT FALSE
          AND (e.nearest_facility_distance_m IS NULL OR e.nearest_facility_distance_m > 2000)
        GROUP BY 1, 2 HAVING count(*) FILTER (WHERE e.last_detected >= :since) >= :min
        ORDER BY current DESC LIMIT :limit"""), p).mappings().all()
    return {"days": days, "min_events": min_events, "facilities": [dict(r) for r in facilities],
            "places": [dict(r) for r in places], "note": NOTE}


# ---------------------------------------------------------------- facility activity profile
SOURCES = ("osm", "wri_gppd", "gem", "cea")


def facility_profile(db: Session, facility_id: uuid.UUID, within_m: float = 2000) -> dict:
    fac = db.execute(text("SELECT id, name FROM facilities WHERE id = :id"), {"id": facility_id}).first()
    if fac is None:
        raise NotFound("Facility not found")
    now = datetime.now(UTC)
    p = {"id": facility_id, "w": within_m, **_windows(now)}
    counts = db.execute(text("""
        SELECT count(DISTINCT l.event_id) FILTER (WHERE l.distance_m <= 2000) AS within_2km,
               count(DISTINCT l.event_id) FILTER (WHERE l.distance_m <= 10000) AS within_10km,
               count(DISTINCT l.event_id) FILTER (WHERE l.rank = 1) AS attributed
        FROM event_facility_links l WHERE l.facility_id = :id"""), p).mappings().one()
    base = """FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
              WHERE l.facility_id = :id AND l.distance_m <= :w"""
    activity = _summarise(db.execute(text(f"SELECT {_COUNTS} {base}"), p).mappings().one(), now)
    events = db.execute(text(f"SELECT e.frp_max, e.persistence_class, e.id {base}"), p).mappings().all()
    bright = db.execute(text(f"""SELECT max(d.brightness) AS b FROM thermal_detections d
                                 WHERE d.event_id IN (SELECT e.id {base}) GROUP BY d.event_id"""), p).scalars().all()
    hours = db.execute(text(f"""SELECT extract(hour FROM d.acq_datetime)::int AS hour, d.daynight, count(*) AS n
                                FROM thermal_detections d WHERE d.event_id IN (SELECT e.id {base}) GROUP BY 1, 2 ORDER BY 1"""), p).mappings().all()
    weekly = db.execute(text(f"""SELECT date_trunc('week', e.last_detected) AS week, count(*) AS events,
                                        COALESCE(sum(e.observation_count), 0) AS detections
                                 {base} GROUP BY 1 ORDER BY 1"""), p).mappings().all()
    classes = db.execute(text(f"SELECT e.classification AS k, count(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC"), p).mappings().all()
    src = db.execute(text("""SELECT source_id, external_id, name, dataset_version FROM facility_sources WHERE facility_id = :id"""),
                     {"id": facility_id}).mappings().all()
    registry = db.execute(text("""SELECT source_id, station_key, name, match_status, coordinate_source FROM registry_stations
                                  WHERE facility_id = :id"""), {"id": facility_id}).mappings().all()
    by_source = {s: [dict(r) for r in src if r["source_id"] == s] for s in SOURCES}
    for r in registry:
        by_source.setdefault(r["source_id"], []).append({"source_id": r["source_id"], "external_id": r["station_key"], "name": r["name"],
                                                         "match_status": r["match_status"]})
    pers: dict[str, int] = {}
    for e in events:
        pers[e["persistence_class"] or "unclassified"] = pers.get(e["persistence_class"] or "unclassified", 0) + 1
    return {
        "within_m": within_m, "counts": dict(counts), "activity": activity,
        "comparison": {
            "current_week": activity["this_week"], "previous_week": activity["previous_week"],
            "weekly_average": activity["weekly_average"], "current_30_days": activity["last_30_days"],
            "previous_30_days": activity["previous_30_days"],
            "note": "Observed activity, not risk. An alert rule being met is a rule condition, not an established cause.",
        },
        "distributions": {
            "frp": _hist([e["frp_max"] for e in events], FRP_BINS),
            "brightness": _hist(list(bright), BRIGHT_BINS),
            "persistence": [{"key": k, "n": n} for k, n in sorted(pers.items(), key=lambda kv: -kv[1])],
            "classifications": _dist(classes),
            "hour_of_day": [dict(h) for h in hours],
        },
        "weekly": [dict(w) for w in weekly],
        "source_agreement": {
            "sources": {s: {"present": bool(by_source.get(s)), "records": by_source.get(s, [])} for s in SOURCES},
            "count": sum(1 for s in SOURCES if by_source.get(s)),
            "note": ("Multiple sources provide stronger provenance for the facility record; they do not prove that the "
                     "facility caused a thermal event."),
        },
        "note": NOTE,
    }

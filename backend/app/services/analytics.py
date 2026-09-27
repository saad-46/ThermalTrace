"""Dashboard and analytics aggregates with shared, server-side filters.

Every figure is an aggregate query over the filtered events (time range on last_detected, India, optional state,
district, facility, classification). Nothing is loaded into the browser and nothing is estimated: an empty filter
returns zeros and empty lists. Counts are FIRMS-derived events, not verified incidents.
"""
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

_CACHE: dict[tuple, tuple[float, object]] = {}
CACHE_SECONDS = 60


def cached(name: str, f: "Filters", fn):
    """Dashboard aggregates are re-requested by every open screen; recompute at most once a minute per filter set."""
    import time

    key = (name, f.since.replace(second=0, microsecond=0), f.until.replace(second=0, microsecond=0), f.state, f.district,
           f.facility_id, tuple(f.classification))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fn()
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = (time.monotonic(), value)
    return value


@dataclass
class Filters:
    since: datetime
    until: datetime
    state: str | None = None
    district: str | None = None
    facility_id: uuid.UUID | None = None
    classification: list[str] = field(default_factory=list)

    @classmethod
    def make(cls, days: int | None, since: datetime | None, until: datetime | None, state: str | None, district: str | None,
             facility_id: uuid.UUID | None, classification: list[str] | None) -> "Filters":
        until = until or datetime.now(UTC)
        since = since or (until - timedelta(days=days or 30))
        return cls(since, until, state or None, district or None, facility_id, list(classification or []))

    def where(self) -> tuple[str, dict]:
        clauses = ["e.last_detected >= :since", "e.last_detected <= :until", "e.in_india IS NOT FALSE", "e.data_mode <> 'demo'"]
        p: dict = {"since": self.since, "until": self.until}
        if self.state:
            clauses.append("(e.admin_state = :state OR e.place_admin1 = :state)")
            p["state"] = self.state
        if self.district:
            clauses.append("(lower(e.admin_district) = lower(:district) OR e.place_name = :district)")
            p["district"] = self.district
        if self.facility_id:
            clauses.append("EXISTS (SELECT 1 FROM event_facility_links l WHERE l.event_id = e.id AND l.facility_id = :fid AND l.distance_m <= 2000)")
            p["fid"] = self.facility_id
        if self.classification:
            clauses.append("e.classification = ANY(:cls)")
            p["cls"] = self.classification
        return " AND ".join(clauses), p

    def describe(self) -> dict:
        return {"since": self.since, "until": self.until, "state": self.state, "district": self.district,
                "facility_id": self.facility_id, "classification": self.classification}


def overview(db: Session, f: Filters) -> dict:
    where, p = f.where()
    totals = db.execute(text(f"""
        SELECT count(*) AS events, COALESCE(sum(e.observation_count), 0) AS detections,
               count(*) FILTER (WHERE e.status = 'active') AS active,
               count(*) FILTER (WHERE e.review_status IN ('under_review', 'escalated')) AS active_investigations,
               count(*) FILTER (WHERE e.confidence_state = 'INSUFFICIENT_EVIDENCE' AND e.review_status = 'unreviewed') AS needs_review,
               count(*) FILTER (WHERE e.review_status = 'analyst_confirmed' OR (e.confidence_state = 'CONFIRMED'
                                  AND e.review_status NOT IN ('analyst_rejected', 'false_positive'))) AS confirmed,
               count(*) FILTER (WHERE e.review_status IN ('analyst_rejected', 'false_positive')) AS rejected,
               count(*) FILTER (WHERE e.review_status = 'reviewed') AS reviewed,
               count(*) FILTER (WHERE e.priority_score >= 70 AND e.review_status IN ('unreviewed', 'under_review')) AS high_priority_queue,
               count(*) FILTER (WHERE e.persistence_class = 'persistent') AS persistent
        FROM thermal_events e WHERE {where}"""), p).mappings().one()
    recurring = db.execute(text(f"""
        SELECT count(*) FROM (SELECT l.facility_id FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id
                              WHERE {where} AND l.distance_m <= 2000 GROUP BY l.facility_id HAVING count(DISTINCT e.id) >= 3) x"""),
        p).scalar_one()
    jobs = db.execute(text("""SELECT count(*) FILTER (WHERE status = 'running') AS running, count(*) FILTER (WHERE status = 'queued') AS queued,
                                     max(finished_at) FILTER (WHERE status = 'failed') AS last_failure FROM jobs""")).mappings().one()
    return {"filters": f.describe(), "totals": dict(totals), "recurring_facilities": recurring,
            "evidence_coverage": cached("coverage", f, lambda: evidence_coverage(db, f)), "processing": dict(jobs),
            "note": "Counts are FIRMS-derived events in the selected range, not verified incidents. Triage priority orders the review queue; it is not a risk score."}


def series(db: Session, f: Filters) -> dict:
    where, p = f.where()
    span = (f.until - f.since).days
    bucket = "day" if span <= 120 else "week" if span <= 730 else "month"
    rows = db.execute(text(f"""
        SELECT date_trunc('{bucket}', e.last_detected) AS bucket, COALESCE(e.classification, 'unclassified') AS classification,
               count(*) AS events, COALESCE(sum(e.observation_count), 0) AS detections
        FROM thermal_events e WHERE {where} GROUP BY 1, 2 ORDER BY 1"""), p).mappings().all()
    return {"bucket": bucket, "rows": [dict(r) for r in rows]}


_FRP_BINS = "ARRAY[0, 5, 10, 25, 50, 100, 250]::float8[]"
_DUR_BINS = "ARRAY[0, 6, 24, 72, 168, 720]::float8[]"


def distributions(db: Session, f: Filters) -> dict:
    where, p = f.where()
    q = lambda sql: [dict(r) for r in db.execute(text(sql), p).mappings().all()]  # noqa: E731
    return {
        "classification": q(f"SELECT COALESCE(e.classification, 'unclassified') AS key, count(*) AS n FROM thermal_events e WHERE {where} GROUP BY 1 ORDER BY 2 DESC"),
        "persistence": q(f"SELECT COALESCE(e.persistence_class, 'unprocessed') AS key, count(*) AS n FROM thermal_events e WHERE {where} GROUP BY 1 ORDER BY 2 DESC"),
        "confidence_state": q(f"SELECT COALESCE(e.confidence_state, 'UNPROCESSED') AS key, count(*) AS n FROM thermal_events e WHERE {where} GROUP BY 1 ORDER BY 2 DESC"),
        "frp": q(f"""SELECT width_bucket(e.frp_max, {_FRP_BINS}) AS bin, count(*) AS n FROM thermal_events e
                     WHERE {where} AND e.frp_max IS NOT NULL GROUP BY 1 ORDER BY 1"""),
        "frp_bins": [0, 5, 10, 25, 50, 100, 250],
        "duration": q(f"""SELECT width_bucket(e.duration_hours, {_DUR_BINS}) AS bin, count(*) AS n FROM thermal_events e
                          WHERE {where} AND e.duration_hours IS NOT NULL GROUP BY 1 ORDER BY 1"""),
        "duration_bins_hours": [0, 6, 24, 72, 168, 720],
    }


def geography(db: Session, f: Filters) -> dict:
    where, p = f.where()
    states = db.execute(text(f"""
        SELECT COALESCE(e.admin_state, e.place_admin1) AS state, count(*) AS events, COALESCE(sum(e.observation_count), 0) AS detections,
               count(*) FILTER (WHERE e.persistence_class = 'persistent') AS persistent
        FROM thermal_events e WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 40"""), p).mappings().all()
    districts = db.execute(text(f"""
        SELECT e.admin_district AS district, COALESCE(e.admin_state, e.place_admin1) AS state, count(*) AS events
        FROM thermal_events e WHERE {where} AND e.admin_district IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30"""), p).mappings().all()
    cells = db.execute(text(f"""
        SELECT round(e.latitude::numeric, 0) AS lat, round(e.longitude::numeric, 0) AS lon, count(*) AS events
        FROM thermal_events e WHERE {where} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 400"""), p).mappings().all()
    return {"states": [dict(r) for r in states], "districts": [dict(r) for r in districts], "density_1deg": [dict(r) for r in cells],
            "note": "States come from reverse geocoding or the offline place index; districts only from geocoded (enriched) events."}


def evidence_coverage(db: Session, f: Filters) -> dict:
    """How many filtered events have each evidence stage, by the same rules as the event page and alerts
    (services.evidence_rules). Evidence availability, not confidence."""
    from app.services import evidence_rules

    where, p = f.where()
    db.execute(text("SET LOCAL work_mem = '64MB'"))  # this transaction only: lets the joins hash in memory
    r = dict(db.execute(text(evidence_rules.coverage_sql(where)), p).mappings().one())
    r["mean_stages"] = round(sum(r[k] for k in evidence_rules.STAGE_KEYS) / r["events"], 1) if r["events"] else None
    r["stages_total"] = evidence_rules.TOTAL
    r["note"] = ("Evidence availability across events, not confidence. Weather and imagery are retrieved for the "
                 "highest-priority events first.")
    return r


def facility_activity(db: Session, f: Filters, limit: int = 20) -> list[dict]:
    where, p = f.where()
    return [dict(r) for r in db.execute(text(f"""
        SELECT fa.id, fa.name, fa.facility_type, count(DISTINCT e.id) AS events,
               count(DISTINCT e.id) FILTER (WHERE l.rank = 1) AS attributed, max(e.frp_max) AS frp_max
        FROM event_facility_links l JOIN thermal_events e ON e.id = l.event_id JOIN facilities fa ON fa.id = l.facility_id
        WHERE {where} AND l.distance_m <= 2000 GROUP BY fa.id ORDER BY events DESC LIMIT :limit"""), {**p, "limit": limit}).mappings()]


def filter_options(db: Session) -> dict:
    states = db.execute(text("""
        SELECT COALESCE(admin_state, place_admin1) AS state, count(*) AS events FROM thermal_events
        WHERE in_india IS NOT FALSE AND COALESCE(admin_state, place_admin1) IS NOT NULL GROUP BY 1 ORDER BY 1""")).mappings().all()
    return {"states": [dict(r) for r in states]}


def districts_for(db: Session, state: str) -> list[dict]:
    return [dict(r) for r in db.execute(text("""
        SELECT admin_district AS district, count(*) AS events FROM thermal_events
        WHERE (admin_state = :s OR place_admin1 = :s) AND admin_district IS NOT NULL AND in_india IS NOT FALSE
        GROUP BY 1 ORDER BY 1"""), {"s": state}).mappings()]

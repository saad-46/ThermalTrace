"""Facility attribution — distance-ranked evidence, never a binary inside/outside match.

attribution_score = relevance(type) × exp(-distance / DECAY_M) × facility.confidence × status_factor

relevance reflects how plausibly that facility type emits detectable thermal anomalies
(flares, furnaces, kilns); status_factor down-weights retired/cancelled facilities.
"""
import math
import uuid

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.facilities import EventFacilityLink

DECAY_M = 1500.0
TYPE_RELEVANCE = {
    "flare_site": 1.0, "oil_gas": 0.95, "refinery": 0.95, "steel_plant": 0.9, "power_plant_coal": 0.8,
    "cement_plant": 0.75, "chemical_plant": 0.7, "coal_mine": 0.85, "mine": 0.5, "landfill": 0.55,
    "power_plant_gas": 0.6, "factory": 0.45, "industrial_area": 0.4, "power_plant_other": 0.2, "rail": 0.1,
    "other": 0.2,
}
_INACTIVE = ("retired", "cancelled", "shelved", "mothballed", "closed")

_CANDIDATES = text(
    """
    SELECT f.id, f.name, f.facility_type, f.status, f.confidence, f.primary_source, f.source_count,
           ST_Distance(f.geom, e.geom) AS distance_m,
           degrees(ST_Azimuth(e.geom::geometry, f.geom::geometry)) AS bearing
    FROM thermal_events e
    JOIN facilities f ON ST_DWithin(f.geom, e.geom, :radius)
    WHERE e.id = :event_id
    ORDER BY distance_m
    LIMIT 25
    """
)


def status_factor(status: str | None) -> float:
    s = (status or "").lower()
    return 0.3 if any(k in s for k in _INACTIVE) else 1.0


def attribution_score(facility_type: str, distance_m: float, confidence: float, status: str | None) -> float:
    rel = TYPE_RELEVANCE.get(facility_type, 0.2)
    return round(rel * math.exp(-max(distance_m, 0.0) / DECAY_M) * confidence * status_factor(status), 4)


def attribute_event(db: Session, event_id: uuid.UUID) -> list[dict]:
    rows = db.execute(_CANDIDATES, {"event_id": event_id, "radius": settings.attribution_radius_m}).mappings().all()
    ranked = sorted(
        (
            {**dict(r), "score": attribution_score(r["facility_type"], r["distance_m"], r["confidence"], r["status"])}
            for r in rows
        ),
        key=lambda r: (-r["score"], r["distance_m"]),
    )
    db.execute(delete(EventFacilityLink).where(EventFacilityLink.event_id == event_id))
    for rank, r in enumerate(ranked[:8], start=1):
        db.add(EventFacilityLink(event_id=event_id, facility_id=r["id"], distance_m=r["distance_m"],
                                 bearing_deg=r["bearing"], rank=rank, attribution_score=r["score"]))
    return ranked

"""Facility consolidation across sources (OSM, GEM, CEA, WRI GPPD).

A source record is upserted into facility_sources by (source_id, external_id). If it has no
facility yet, it is matched to an existing facility of a compatible type within MATCH_RADIUS_M
(from a *different* source); otherwise a new facility is created. When independent sources
agree, confidence rises: c = 1 − Π(1 − c_source), capped at 0.95.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.facilities import Facility, FacilitySource

SOURCE_CONFIDENCE = {"osm": 0.5, "wri_gppd": 0.6, "gem": 0.7, "cea": 0.75, "demo": 0.3}
TYPE_GROUPS = {
    "oil": {"refinery", "oil_gas", "flare_site"},
    "power": {"power_plant_coal", "power_plant_gas", "power_plant_other"},
    "heavy": {"steel_plant", "cement_plant", "chemical_plant", "factory", "industrial_area"},
    "mine": {"mine", "coal_mine"},
    "waste": {"landfill"},
}
LARGE_TYPES = {"refinery", "oil_gas", "power_plant_coal", "power_plant_gas", "steel_plant", "cement_plant", "coal_mine"}
# Specific registry types win over generic OSM ones when merging.
TYPE_SPECIFICITY = ["industrial_area", "factory", "other", "power_plant_other", "mine"]


def _group(ftype: str) -> str:
    return next((g for g, members in TYPE_GROUPS.items() if ftype in members), "other")


@dataclass
class SourceRecord:
    source_id: str
    external_id: str
    name: str | None
    facility_type: str
    source_type: str | None
    latitude: float
    longitude: float
    operator: str | None = None
    status: str | None = None
    capacity_value: float | None = None
    capacity_unit: str | None = None
    country: str | None = None
    state: str | None = None
    district: str | None = None
    source_url: str | None = None
    dataset_version: str | None = None
    published_at: date | None = None
    raw: dict | None = None
    footprint_wkt: str | None = None
    subtype: str | None = None


# Registry statuses meaning the plant was never built (GEM). They must not overwrite a facility that other sources
# show to exist (e.g. a cancelled expansion listed at an operating plant's location).
NEVER_BUILT = ("cancelled", "shelved", "announced", "pre-permit", "permitted")


def _apply_registry_status(db: Session, fac: Facility, rec: "SourceRecord") -> None:
    if rec.source_id not in ("gem", "cea") or not rec.status:
        return
    status = rec.status.strip().lower()
    if status in NEVER_BUILT:
        others = db.execute(select(FacilitySource.source_id).where(FacilitySource.facility_id == fac.id,
                                                                   FacilitySource.source_id != rec.source_id)).first()
        if others is not None:
            if (fac.status or "").lower() in NEVER_BUILT:
                fac.status = None  # other sources show it exists; its operating status is unknown
            return
    fac.status = status


_MATCH = text(
    """
    SELECT f.id, f.facility_type, ST_Distance(f.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS d
    FROM facilities f
    WHERE ST_DWithin(f.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
      AND f.facility_type = ANY(:types)
      AND NOT EXISTS (SELECT 1 FROM facility_sources s WHERE s.facility_id = f.id AND s.source_id = :source)
    ORDER BY d LIMIT 1
    """
)


def _recompute_confidence(db: Session, facility: Facility) -> None:
    sources = db.execute(select(FacilitySource.source_id).where(FacilitySource.facility_id == facility.id)).scalars().all()
    miss = 1.0
    for s in set(sources):
        miss *= 1 - SOURCE_CONFIDENCE.get(s, 0.4)
    facility.confidence = round(min(1 - miss, 0.95), 3)
    facility.source_count = len(set(sources))


def upsert(db: Session, rec: SourceRecord) -> tuple[Facility, bool]:
    """Returns (facility, created_new_source_record)."""
    now = datetime.now(UTC)
    existing = db.execute(
        select(FacilitySource).where(FacilitySource.source_id == rec.source_id, FacilitySource.external_id == rec.external_id)
    ).scalar_one_or_none()
    if existing is not None:
        # Re-import of the same source record: refresh what the source says about it.
        existing.retrieved_at = now
        existing.dataset_version = rec.dataset_version or existing.dataset_version
        existing.name = rec.name or existing.name
        existing.raw = rec.raw or existing.raw
        fac = db.get(Facility, existing.facility_id)
        _apply_registry_status(db, fac, rec)
        if fac.primary_source == rec.source_id and rec.capacity_value is not None:
            fac.capacity_value = rec.capacity_value
        fac.subtype = fac.subtype or rec.subtype
        return fac, False

    fac = None
    group_types = list(TYPE_GROUPS.get(_group(rec.facility_type), {rec.facility_type}))
    radius = 1500 if rec.facility_type in LARGE_TYPES else 600
    match = db.execute(_MATCH, {"lat": rec.latitude, "lon": rec.longitude, "radius": radius, "types": group_types,
                                "source": rec.source_id}).first()
    if match:
        fac = db.get(Facility, match.id)
        if TYPE_SPECIFICITY.count(fac.facility_type) and not TYPE_SPECIFICITY.count(rec.facility_type):
            fac.facility_type = rec.facility_type
        fac.name = fac.name or rec.name
        fac.operator = fac.operator or rec.operator
        fac.capacity_value = fac.capacity_value or rec.capacity_value
        fac.capacity_unit = fac.capacity_unit or rec.capacity_unit
        fac.state = fac.state or rec.state
        fac.subtype = fac.subtype or rec.subtype
        fac.district = fac.district or rec.district
    else:
        fac = Facility(
            name=rec.name, facility_type=rec.facility_type, subtype=rec.subtype, operator=rec.operator,
            status=rec.status.strip().lower() if rec.status and rec.source_id in ("gem", "cea") else rec.status,
            capacity_value=rec.capacity_value, capacity_unit=rec.capacity_unit, country=rec.country, state=rec.state,
            district=rec.district, geom=f"SRID=4326;POINT({rec.longitude} {rec.latitude})",
            footprint=f"SRID=4326;{rec.footprint_wkt}" if rec.footprint_wkt else None,
            latitude=rec.latitude, longitude=rec.longitude, confidence=SOURCE_CONFIDENCE.get(rec.source_id, 0.4),
            primary_source=rec.source_id, source_count=1, attributes={},
        )
        db.add(fac)
        db.flush()
    if match:
        _apply_registry_status(db, fac, rec)
    db.add(FacilitySource(
        facility_id=fac.id, source_id=rec.source_id, external_id=rec.external_id, name=rec.name,
        source_type=rec.source_type, source_url=rec.source_url, dataset_version=rec.dataset_version,
        published_at=rec.published_at, retrieved_at=now, raw=rec.raw or {},
    ))
    db.flush()
    _recompute_confidence(db, fac)
    return fac, True

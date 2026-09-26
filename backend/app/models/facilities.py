import uuid
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import created_at, updated_at, uuid_pk

FACILITY_TYPES = (
    "refinery",
    "oil_gas",
    "power_plant_coal",
    "power_plant_gas",
    "power_plant_other",
    "steel_plant",
    "cement_plant",
    "chemical_plant",
    "mine",
    "coal_mine",
    "landfill",
    "flare_site",
    "factory",
    "industrial_area",
    "rail",
    "other",
)


class Facility(Base):
    """A consolidated facility. Several source records may back one facility (facility_sources)."""

    __tablename__ = "facilities"
    __table_args__ = (
        Index("ix_facilities_geom", "geom", postgresql_using="gist"),
        Index("ix_facilities_type", "facility_type"),
        Index("ix_facilities_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str | None] = mapped_column(String(300))
    facility_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(80))
    operator: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str | None] = mapped_column(String(40))  # operating / construction / retired / unknown
    capacity_value: Mapped[float | None] = mapped_column(Float)
    capacity_unit: Mapped[str | None] = mapped_column(String(24))
    country: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120))
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
    footprint = mapped_column(Geography("GEOMETRY", srid=4326, spatial_index=False))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # 0..1 — rises when independent sources agree; see services/facility_merge.py
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    primary_source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class FacilitySource(Base):
    __tablename__ = "facility_sources"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_facility_source_external"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str | None] = mapped_column(String(120))  # raw type string from the source
    source_url: Mapped[str | None] = mapped_column(Text)
    dataset_version: Mapped[str | None] = mapped_column(String(80))
    published_at: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class FacilityRelationship(Base):
    __tablename__ = "facility_relationships"
    __table_args__ = (UniqueConstraint("facility_a", "facility_b", "relation", name="uq_facility_relationship"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    facility_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"))
    facility_b: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(24), nullable=False)  # part_of | adjacent
    distance_m: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at()


class EventFacilityLink(Base):
    """Distance-ranked facility context for an event (attribution evidence, never a binary match)."""

    __tablename__ = "event_facility_links"
    __table_args__ = (UniqueConstraint("event_id", "facility_id", name="uq_event_facility"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    bearing_deg: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    attribution_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = created_at()


class LandContext(Base):
    """OSM land-use / infrastructure features found around an event (Overpass enrichment)."""

    __tablename__ = "land_context"
    __table_args__ = (UniqueConstraint("event_id", "osm_type", "osm_id", name="uq_land_context_feature"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    osm_type: Mapped[str] = mapped_column(String(10), nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # OSM ids exceed 2^31
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # farmland / forest / residential / ...
    name: Mapped[str | None] = mapped_column(Text)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

import uuid
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import created_at, updated_at, uuid_pk

DATA_MODES = ("live", "historical", "demo")

event_public_seq = Sequence("thermal_event_public_seq")


class ThermalDetection(Base):
    """One FIRMS fire pixel, normalized across sensors. Immutable after ingest except event_id."""

    __tablename__ = "thermal_detections"
    __table_args__ = (
        UniqueConstraint("dataset", "latitude", "longitude", "acq_datetime", name="uq_detection_natural_key"),
        CheckConstraint(f"data_mode IN {DATA_MODES}", name="ck_detection_data_mode"),
        Index("ix_detections_geom", "geom", postgresql_using="gist"),
        Index("ix_detections_unassigned", "acq_datetime", postgresql_where="event_id IS NULL"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    acq_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    acq_date: Mapped[date] = mapped_column(Date, nullable=False)
    acq_time: Mapped[str] = mapped_column(String(4), nullable=False)
    sensor: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # MODIS | VIIRS
    satellite: Mapped[str] = mapped_column(String(16), nullable=False)  # Terra/Aqua/N/N20/N21
    dataset: Mapped[str] = mapped_column(String(48), nullable=False, index=True)  # e.g. VIIRS_NOAA21_NRT
    confidence_raw: Mapped[str | None] = mapped_column(String(16))
    confidence_pct: Mapped[float | None] = mapped_column(Float, index=True)
    frp: Mapped[float | None] = mapped_column(Float)
    brightness: Mapped[float | None] = mapped_column(Float)  # MODIS brightness / VIIRS bright_ti4 (K)
    brightness_2: Mapped[float | None] = mapped_column(Float)  # MODIS bright_t31 / VIIRS bright_ti5 (K)
    scan: Mapped[float | None] = mapped_column(Float)
    track: Mapped[float | None] = mapped_column(Float)
    daynight: Mapped[str | None] = mapped_column(String(1))
    version: Mapped[str | None] = mapped_column(String(16))
    data_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)  # URL / file the row came from (key redacted)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = created_at()


class ThermalEvent(Base):
    """A spatio-temporal cluster of detections: the unit analysts investigate."""

    __tablename__ = "thermal_events"
    __table_args__ = (
        CheckConstraint(f"data_mode IN {DATA_MODES}", name="ck_event_data_mode"),
        Index("ix_events_geom", "geom", postgresql_using="gist"),
        Index("ix_events_last_detected", "last_detected"),
        Index("ix_events_classification", "classification"),
        Index("ix_events_persistence", "persistence_class"),
        Index("ix_events_confidence", "confidence_score"),
        Index("ix_events_status", "status", "review_status"),
        Index("ix_events_district_trgm", "admin_district", postgresql_using="gin", postgresql_ops={"admin_district": "gin_trgm_ops"}),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    public_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
    footprint = mapped_column(Geography("POLYGON", srid=4326, spatial_index=False))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sensor_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sensors: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, default=list)
    datasets: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    days_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    frp_max: Mapped[float | None] = mapped_column(Float)
    frp_mean: Mapped[float | None] = mapped_column(Float)
    frp_sum: Mapped[float | None] = mapped_column(Float)
    frp_std: Mapped[float | None] = mapped_column(Float)
    confidence_mean: Mapped[float | None] = mapped_column(Float)
    night_fraction: Mapped[float | None] = mapped_column(Float)

    # activity: active (seen within gap tolerance) | dormant | closed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # analyst workflow
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    persistence_class: Mapped[str | None] = mapped_column(String(16))
    persistence_score: Mapped[float | None] = mapped_column(Float)
    persistence_metrics: Mapped[dict | None] = mapped_column(JSONB)

    classification: Mapped[str | None] = mapped_column(String(32))
    classification_probability: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    confidence_state: Mapped[str | None] = mapped_column(String(32))
    confidence_components: Mapped[dict | None] = mapped_column(JSONB)
    data_quality: Mapped[str | None] = mapped_column(String(16))
    data_quality_detail: Mapped[dict | None] = mapped_column(JSONB)
    fingerprint: Mapped[dict | None] = mapped_column(JSONB)
    # Triage priority (0-100): orders the analyst queue. Not a risk/threat score. See processing/priority.py.
    priority_score: Mapped[float | None] = mapped_column(Float, index=True)
    priority_components: Mapped[dict | None] = mapped_column(JSONB)

    nearest_facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"), index=True
    )
    nearest_facility_distance_m: Mapped[float | None] = mapped_column(Float)
    admin_state: Mapped[str | None] = mapped_column(String(120), index=True)
    admin_district: Mapped[str | None] = mapped_column(String(120), index=True)
    country: Mapped[str | None] = mapped_column(String(80))

    enrichment_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ThermalObservation(Base):
    """Per-event, per-UTC-day aggregate of detections — powers timeline, evolution and persistence."""

    __tablename__ = "thermal_observations"
    __table_args__ = (UniqueConstraint("event_id", "obs_date", name="uq_observation_event_day"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    obs_date: Mapped[date] = mapped_column(Date, nullable=False)
    detection_count: Mapped[int] = mapped_column(Integer, nullable=False)
    frp_max: Mapped[float | None] = mapped_column(Float)
    frp_sum: Mapped[float | None] = mapped_column(Float)
    sensors: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    night_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    spread_m: Mapped[float | None] = mapped_column(Float)  # max distance of that day's pixels from centroid

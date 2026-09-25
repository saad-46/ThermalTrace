import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import uuid_pk


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (UniqueConstraint("event_id", "kind", "observed_at", name="uq_weather_event_kind_time"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # at_last_detection | current
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), nullable=False)
    dataset: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. open-meteo archive (ERA5) / forecast
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)  # meteorological: direction wind comes FROM
    precipitation_mm: Mapped[float | None] = mapped_column(Float)
    pressure_hpa: Mapped[float | None] = mapped_column(Float)
    weather_code: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(80))
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SatelliteObservation(Base):
    __tablename__ = "satellite_observations"
    __table_args__ = (UniqueConstraint("event_id", "provider", "item_id", name="uq_satellite_event_item"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # earth-search | cdse
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), nullable=False)
    collection: Mapped[str] = mapped_column(String(60), nullable=False)
    item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(40))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float)
    processing_level: Mapped[str | None] = mapped_column(String(20))
    relation: Mapped[str] = mapped_column(String(12), nullable=False)  # before | during | after | latest
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    item_url: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[list | None] = mapped_column(JSONB)
    assets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

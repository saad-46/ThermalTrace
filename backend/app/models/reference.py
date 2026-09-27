"""Geographic reference data (India boundary, states) and registry stations (e.g. CEA) with their provenance."""
import uuid
from datetime import date, datetime

from geoalchemy2 import Geography, Geometry
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import uuid_pk


class Boundary(Base):
    """A country outline used for spatial filtering and the map (India: Natural Earth, India point of view)."""

    __tablename__ = "boundaries"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(160))
    license: Mapped[str] = mapped_column(String(120), nullable=False)
    pov: Mapped[str | None] = mapped_column(String(8))
    geom = mapped_column(Geography("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoundaryPart(Base):
    """Subdivided pieces of a boundary: index-assisted point-in-polygon tests."""

    __tablename__ = "boundary_parts"
    __table_args__ = (Index("ix_boundary_parts_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), ForeignKey("boundaries.code", ondelete="CASCADE"), nullable=False, index=True)
    geom = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=False), nullable=False)


class AdminArea(Base):
    """First-level administrative areas (Indian states and union territories)."""

    __tablename__ = "admin_areas"
    __table_args__ = (Index("ix_admin_areas_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str | None] = mapped_column(String(60))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False)


class RegistryStation(Base):
    """A station as listed by an official registry (CEA), whether or not a location could be attached.

    Registry identity and attributes come from the registry. Coordinates, when present, come from a matched facility
    and `coordinate_source` says which source supplied them; the registry itself is never credited with them."""

    __tablename__ = "registry_stations"
    __table_args__ = (
        UniqueConstraint("source_id", "station_key", name="uq_registry_station"),
        Index("ix_registry_stations_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), nullable=False)
    station_key: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)  # thermal | hydro | nuclear
    region: Mapped[str | None] = mapped_column(String(8))
    state: Mapped[str | None] = mapped_column(String(120))
    sector: Mapped[str | None] = mapped_column(String(40))
    organisation: Mapped[str | None] = mapped_column(String(200))
    prime_movers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity_mw: Mapped[float] = mapped_column(Float, nullable=False)
    first_year: Mapped[int | None] = mapped_column(Integer)
    last_year: Mapped[int | None] = mapped_column(Integer)
    units: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_file: Mapped[str] = mapped_column(String(200), nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"),
                                                          index=True)
    match_status: Mapped[str] = mapped_column(String(16), nullable=False)  # matched | ambiguous | unmatched
    match_score: Mapped[float | None] = mapped_column(Float)
    coordinate_source: Mapped[str | None] = mapped_column(String(32))
    coordinate_confidence: Mapped[str | None] = mapped_column(String(16))  # high | medium
    match_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

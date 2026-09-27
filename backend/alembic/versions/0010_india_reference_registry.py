"""India boundary and states, in-India flag on events, registry stations (CEA), per-capability source health

- boundaries / boundary_parts / admin_areas: Natural Earth 1:10m India (India point of view) and its states, loaded
  from app/gis/data (committed, public domain). boundary_parts are subdivided for index-assisted point-in-polygon.
- thermal_events.in_india: set by processing (and backfilled in batches by housekeeping / `app.cli classify-regions`).
- registry_stations: stations as listed by an official registry (CEA), with or without a matched location.
- data_sources.health_detail: e.g. Copernicus authentication and SWIR preview checks recorded separately.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27 06:00:00
"""
import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "boundaries",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source", sa.String(300), nullable=False),
        sa.Column("source_version", sa.String(160)),
        sa.Column("license", sa.String(120), nullable=False),
        sa.Column("pov", sa.String(8)),
        sa.Column("geom", geoalchemy2.Geography("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "boundary_parts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(8), sa.ForeignKey("boundaries.code", ondelete="CASCADE"), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POLYGON", srid=4326, spatial_index=False), nullable=False),
    )
    op.create_index("ix_boundary_parts_code", "boundary_parts", ["code"])
    op.create_index("ix_boundary_parts_geom", "boundary_parts", ["geom"], postgresql_using="gist")
    op.create_table(
        "admin_areas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("country", sa.String(8), nullable=False),
        sa.Column("code", sa.String(16)),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(60)),
        sa.Column("geom", geoalchemy2.Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False),
    )
    op.create_index("ix_admin_areas_country", "admin_areas", ["country"])
    op.create_index("ix_admin_areas_geom", "admin_areas", ["geom"], postgresql_using="gist")
    op.create_table(
        "registry_stations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("station_key", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("region", sa.String(8)),
        sa.Column("state", sa.String(120)),
        sa.Column("sector", sa.String(40)),
        sa.Column("organisation", sa.String(200)),
        sa.Column("prime_movers", postgresql.JSONB, nullable=False),
        sa.Column("unit_count", sa.Integer, nullable=False),
        sa.Column("capacity_mw", sa.Float, nullable=False),
        sa.Column("first_year", sa.Integer),
        sa.Column("last_year", sa.Integer),
        sa.Column("units", postgresql.JSONB, nullable=False),
        sa.Column("source_file", sa.String(200), nullable=False),
        sa.Column("source_date", sa.Date),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("facilities.id", ondelete="SET NULL")),
        sa.Column("match_status", sa.String(16), nullable=False),
        sa.Column("match_score", sa.Float),
        sa.Column("coordinate_source", sa.String(32)),
        sa.Column("coordinate_confidence", sa.String(16)),
        sa.Column("match_detail", postgresql.JSONB, nullable=False),
        sa.Column("flags", postgresql.JSONB, nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "station_key", name="uq_registry_station"),
    )
    op.create_index("ix_registry_stations_facility_id", "registry_stations", ["facility_id"])
    op.add_column("thermal_events", sa.Column("in_india", sa.Boolean()))
    op.execute("CREATE INDEX IF NOT EXISTS ix_thermal_events_in_india ON thermal_events (in_india)")
    op.add_column("data_sources", sa.Column("health_detail", postgresql.JSONB, nullable=False, server_default="{}"))

    # Power plants keep their fuel as subtype (WRI GPPD primary_fuel), so non-combustion plants can be told apart.
    op.execute("""UPDATE facilities f SET subtype = lower(s.raw->>'primary_fuel')
                  FROM facility_sources s
                  WHERE s.facility_id = f.id AND s.source_id = 'wri_gppd' AND f.subtype IS NULL
                    AND s.raw->>'primary_fuel' IS NOT NULL""")

    from app.gis import boundaries
    boundaries.load(Session(bind=op.get_bind()))


def downgrade() -> None:
    op.drop_column("data_sources", "health_detail")
    op.execute("DROP INDEX IF EXISTS ix_thermal_events_in_india")
    op.drop_column("thermal_events", "in_india")
    op.drop_table("registry_stations")
    op.drop_table("admin_areas")
    op.drop_table("boundary_parts")
    op.drop_table("boundaries")

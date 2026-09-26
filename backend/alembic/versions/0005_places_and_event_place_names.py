"""places and event place names

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26 17:13:32.823042
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO data_sources (id, name, kind, homepage, license, access, cadence, status, records_total, "
        "requests_total, requests_failed) VALUES ('geonames', 'GeoNames populated places (cities500)', 'geocoding', "
        "'https://www.geonames.org', 'CC BY 4.0', 'file_import', 'Static download; refreshed on demand', 'unknown', 0, 0, 0) "
        "ON CONFLICT (id) DO NOTHING"
    )
    op.create_geospatial_table('places',
    sa.Column('geonameid', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('admin1', sa.String(length=120), nullable=True),
    sa.Column('country_code', sa.String(length=2), nullable=False),
    sa.Column('population', sa.BigInteger(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('geom', Geography(geometry_type='POINT', srid=4326, spatial_index=False, from_text='ST_GeogFromText', name='geography', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('geonameid')
    )
    op.create_geospatial_index('ix_places_geom', 'places', ['geom'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.add_column('thermal_events', sa.Column('place_name', sa.String(length=200), nullable=True))
    op.add_column('thermal_events', sa.Column('place_admin1', sa.String(length=120), nullable=True))
    op.add_column('thermal_events', sa.Column('place_country', sa.String(length=2), nullable=True))
    op.add_column('thermal_events', sa.Column('place_distance_m', sa.Float(), nullable=True))
    op.create_index('ix_events_place_trgm', 'thermal_events', ['place_name'], postgresql_using='gin',
                    postgresql_ops={'place_name': 'gin_trgm_ops'})


def downgrade() -> None:
    op.drop_index('ix_events_place_trgm', table_name='thermal_events')
    op.drop_column('thermal_events', 'place_distance_m')
    op.drop_column('thermal_events', 'place_country')
    op.drop_column('thermal_events', 'place_admin1')
    op.drop_column('thermal_events', 'place_name')
    op.drop_geospatial_index('ix_places_geom', table_name='places', postgresql_using='gist', column_name='geom')
    op.drop_geospatial_table('places')
    op.execute("DELETE FROM data_sources WHERE id = 'geonames'")

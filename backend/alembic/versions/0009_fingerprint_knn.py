"""nearest-neighbour index for similar events; district index for watchlists

Similar events scored every fingerprint on each request (3.6-7 s on the development database, far longer under
load). The five numeric fingerprint dimensions are indexed as a cube in a GiST index keyed by facility type, so the
nearest events are found with an index-ordered (KNN) scan. Replaces ix_events_fp_facility_type.
Watchlist district items match events case-insensitively; that needed a scan of every event.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27 01:00:00
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

# Must match app.repositories.events._FP_TYPE / _FP_CUBE exactly for the planner to use the index.
FP_TYPE = "coalesce(fingerprint->>'facility_type', '')"
FP_CUBE = ("cube(ARRAY[coalesce((fingerprint->>'intensity')::float8, 0), coalesce((fingerprint->>'persistence')::float8, 0), "
           "coalesce((fingerprint->>'facility_proximity')::float8, 0), coalesce((fingerprint->>'night_share')::float8, 0), "
           "coalesce((fingerprint->>'sensor_agreement')::float8, 0)])")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS cube")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_events_fp_knn ON thermal_events USING gist (({FP_TYPE}), ({FP_CUBE})) "
               "WHERE fingerprint IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_events_fp_facility_type")
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_admin_district_lower ON thermal_events (lower(admin_district))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_admin_district_lower")
    op.execute("DROP INDEX IF EXISTS ix_events_fp_knn")
    # The extensions are left installed: other objects may depend on them.

"""indexes for the slow read paths at full-year scale (~340k events)

Measured on the development database before this migration: model usage count 5.2 s, persistent-source
ranking 4.3 s, event-id search 1.9 s, place search (admin_state) seq scan, priority queue full sort.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-26 21:30:00
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # System health -> model versions: current classifications per model (index-only count).
    op.execute("CREATE INDEX IF NOT EXISTS ix_classifications_current_model ON classifications (primary_model_id) WHERE is_current")
    # Persistent/recurring source ranking: matches the ORDER BY of /analytics/persistent-sources exactly.
    op.execute("""CREATE INDEX IF NOT EXISTS ix_events_persistence_rank ON thermal_events
                  ((persistence_class = 'persistent') DESC, persistence_score DESC, sensor_count DESC, observation_count DESC)
                  WHERE persistence_class IN ('persistent', 'recurring')""")
    # Review queue by triage priority: DESC NULLS LAST cannot use the existing ascending index.
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_priority_rank ON thermal_events (priority_score DESC NULLS LAST, id)")
    # Global search: substring matches on event ids and state names.
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_public_id_trgm ON thermal_events USING gin (public_id gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_state_trgm ON thermal_events USING gin (admin_state gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_events_place_admin1_trgm ON thermal_events USING gin (place_admin1 gin_trgm_ops)")


def downgrade() -> None:
    for name in ("ix_events_place_admin1_trgm", "ix_events_state_trgm", "ix_events_public_id_trgm", "ix_events_priority_rank",
                 "ix_events_persistence_rank", "ix_classifications_current_model"):
        op.execute(f"DROP INDEX IF EXISTS {name}")

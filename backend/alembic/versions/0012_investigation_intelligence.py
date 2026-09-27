"""Investigation intelligence: review status history, advanced alert conditions, search indexes

- analyst_reviews.previous_status / new_status: the event's review status before and after each decision, so the
  review history is explicit (decisions widened to 24 chars for request_evidence / mark_reviewed).
- alert_rules: increase_factor, increase_window_days (parameterise activity_increase), repeat_within_m (repeated
  activity counted by distance to the facility), min_active_days (persistence), min_evidence_stages (evidence
  availability, not confidence).
- Trigram indexes for unified search: facility operator, facility source external ids (registry ids), registry
  station names.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-28 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyst_reviews", sa.Column("previous_status", sa.String(24), nullable=True))
    op.add_column("analyst_reviews", sa.Column("new_status", sa.String(24), nullable=True))
    op.alter_column("analyst_reviews", "decision", type_=sa.String(24), existing_type=sa.String(20), existing_nullable=False)
    op.add_column("alert_rules", sa.Column("increase_factor", sa.Float(), nullable=False, server_default="2"))
    op.add_column("alert_rules", sa.Column("increase_window_days", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("alert_rules", sa.Column("repeat_within_m", sa.Float(), nullable=True))
    op.add_column("alert_rules", sa.Column("min_active_days", sa.Integer(), nullable=True))
    op.add_column("alert_rules", sa.Column("min_evidence_stages", sa.Integer(), nullable=True))
    op.create_index("ix_facilities_operator_trgm", "facilities", ["operator"], postgresql_using="gin",
                    postgresql_ops={"operator": "gin_trgm_ops"})
    op.create_index("ix_facility_sources_external_trgm", "facility_sources", ["external_id"], postgresql_using="gin",
                    postgresql_ops={"external_id": "gin_trgm_ops"})
    op.create_index("ix_registry_stations_name_trgm", "registry_stations", ["name"], postgresql_using="gin",
                    postgresql_ops={"name": "gin_trgm_ops"})


def downgrade() -> None:
    op.drop_index("ix_registry_stations_name_trgm", table_name="registry_stations")
    op.drop_index("ix_facility_sources_external_trgm", table_name="facility_sources")
    op.drop_index("ix_facilities_operator_trgm", table_name="facilities")
    for c in ("min_evidence_stages", "min_active_days", "repeat_within_m", "increase_window_days", "increase_factor"):
        op.drop_column("alert_rules", c)
    op.alter_column("analyst_reviews", "decision", type_=sa.String(20), existing_type=sa.String(24), existing_nullable=False)
    op.drop_column("analyst_reviews", "new_status")
    op.drop_column("analyst_reviews", "previous_status")

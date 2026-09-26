"""raster land cover, imagery analysis, alert activity conditions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26 09:38:26.236567
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The land-cover source must exist before landcover_observations can reference it.
    op.execute(
        "INSERT INTO data_sources (id, name, kind, homepage, license, access, cadence, status, records_total, "
        "requests_total, requests_failed) VALUES ('esa_worldcover', 'ESA WorldCover 10 m 2021 v200', 'landcover', "
        "'https://esa-worldcover.org', 'CC BY 4.0', 'api', 'Static annual product (2021); sampled per event window', "
        "'unknown', 0, 0, 0) ON CONFLICT (id) DO NOTHING"
    )
    op.create_table('imagery_analyses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('finding', sa.String(length=32), nullable=True),
    sa.Column('window_m', sa.Float(), nullable=False),
    sa.Column('before_scene', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after_scene', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('deltas', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('method', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['thermal_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    op.create_table('landcover_observations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.String(length=32), nullable=False),
    sa.Column('product', sa.String(length=80), nullable=False),
    sa.Column('window_m', sa.Float(), nullable=False),
    sa.Column('fractions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('dominant', sa.String(length=32), nullable=True),
    sa.Column('valid_fraction', sa.Float(), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['thermal_events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    op.add_column('alert_rules', sa.Column('min_priority', sa.Integer(), nullable=True))
    op.add_column('alert_rules', sa.Column('min_repeat_events', sa.Integer(), nullable=True))
    op.add_column('alert_rules', sa.Column('repeat_days', sa.Integer(), server_default='30', nullable=False))
    op.add_column('alert_rules', sa.Column('activity_increase', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('alert_rules', 'activity_increase')
    op.drop_column('alert_rules', 'repeat_days')
    op.drop_column('alert_rules', 'min_repeat_events')
    op.drop_column('alert_rules', 'min_priority')
    op.drop_table('landcover_observations')
    op.drop_table('imagery_analyses')
    op.execute("DELETE FROM data_sources WHERE id = 'esa_worldcover'")

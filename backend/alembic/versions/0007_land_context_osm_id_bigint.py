"""land context osm id bigint

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26 19:26:30.789659
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # OpenStreetMap ids have passed 2^31, which made land-use enrichment fail with "integer out of range".
    op.alter_column('land_context', 'osm_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False)


def downgrade() -> None:
    # Rows that do not fit a 32-bit id cannot be kept; they are re-derived by the next enrichment run.
    op.execute("DELETE FROM land_context WHERE osm_id > 2147483647")
    op.alter_column('land_context', 'osm_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False)

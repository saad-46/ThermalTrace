"""Index jobs by event, for per-event enrichment and imagery status on the event page

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27 12:00:00
"""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_event ON jobs ((payload->>'event_id')) WHERE payload ? 'event_id'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_event")

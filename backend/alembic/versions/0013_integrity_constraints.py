"""Integrity constraints that were enforced only by application code

- classifications: at most one current classification per event (partial unique index). Two concurrent analyses of
  the same event could otherwise leave two rows with is_current = true.
- alert_deliveries: one delivery record per alert and channel, so a retried job can never record (or send) a channel
  twice for the same alert.

Both were verified duplicate-free on the development database before this migration was written. Apply it when no
processing pass is running (the unique index on classifications briefly blocks writes to that table).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-28 20:00:00
"""
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_classifications_event_current", "classifications", ["event_id"], unique=True,
                    postgresql_where="is_current")
    op.create_unique_constraint("uq_alert_deliveries_alert_channel", "alert_deliveries", ["alert_id", "channel"])


def downgrade() -> None:
    op.drop_constraint("uq_alert_deliveries_alert_channel", "alert_deliveries", type_="unique")
    op.drop_index("uq_classifications_event_current", table_name="classifications")

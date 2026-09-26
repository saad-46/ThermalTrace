"""demo accounts

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26 17:39:07.686155
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_demo', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    # Without the flag, demo accounts would look like ordinary accounts: disable them before dropping it.
    op.execute("UPDATE users SET is_active = false WHERE is_demo")
    op.drop_column('users', 'is_demo')

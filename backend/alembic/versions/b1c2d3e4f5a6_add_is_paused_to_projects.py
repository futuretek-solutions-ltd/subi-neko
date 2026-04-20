"""add is_paused to projects

Revision ID: b1c2d3e4f5a6
Revises: a2b3c4d5e6f7
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('is_paused', sa.Integer(), nullable=False, server_default='0'))
    # Migrate any existing rows that had status='paused' back to 'processing'
    op.execute("UPDATE projects SET is_paused = 1, status = 'processing' WHERE status = 'paused'")


def downgrade() -> None:
    op.execute("UPDATE projects SET status = 'paused' WHERE is_paused = 1")
    op.drop_column('projects', 'is_paused')

"""add original ai translation to subtitle events

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('subtitle_events', sa.Column('original_ai_translated_text', sa.Text(), nullable=True))
    op.execute(
        "UPDATE subtitle_events "
        "SET original_ai_translated_text = translated_text "
        "WHERE translated_text IS NOT NULL AND is_user_edited = 0"
    )


def downgrade() -> None:
    op.drop_column('subtitle_events', 'original_ai_translated_text')

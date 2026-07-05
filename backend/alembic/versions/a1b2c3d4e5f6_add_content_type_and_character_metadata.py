"""add content_type classification, character metadata, speaker coverage

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('subtitle_events', sa.Column('content_type', sa.Text(), nullable=False, server_default='dialogue'))
    op.add_column('subtitle_events', sa.Column('content_type_reason', sa.Text(), nullable=True))
    op.create_index(
        'idx_subtitle_events_file_content_type',
        'subtitle_events',
        ['file_id', 'content_type'],
    )

    op.add_column('subtitle_chunks', sa.Column('content_type', sa.Text(), nullable=False, server_default='dialogue'))

    op.add_column('project_characters', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('project_characters', sa.Column('voice_actor', sa.Text(), nullable=True))
    op.add_column('project_characters', sa.Column('character_type', sa.Text(), nullable=True))

    op.add_column('projects', sa.Column('speaker_coverage', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'speaker_coverage')

    op.drop_column('project_characters', 'character_type')
    op.drop_column('project_characters', 'voice_actor')
    op.drop_column('project_characters', 'description')

    op.drop_column('subtitle_chunks', 'content_type')

    op.drop_index('idx_subtitle_events_file_content_type', table_name='subtitle_events')
    op.drop_column('subtitle_events', 'content_type_reason')
    op.drop_column('subtitle_events', 'content_type')

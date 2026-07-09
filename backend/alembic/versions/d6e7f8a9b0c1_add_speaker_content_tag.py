"""add project_speakers.content_tag

A speaker can be tagged as sign/karaoke/song; the chunk planner then
re-types that speaker's events so they land in the matching content-type
partition (and e.g. auto-skip when TRANSLATE_KARAOKE is off).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'project_speakers',
        sa.Column('content_tag', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('project_speakers') as batch:
        batch.drop_column('content_tag')

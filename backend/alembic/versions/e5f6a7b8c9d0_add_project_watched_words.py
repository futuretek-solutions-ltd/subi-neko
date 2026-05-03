"""add project watched words

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_watched_words',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('word', sa.Text(), nullable=False),
        sa.Column('word_type', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.UniqueConstraint('project_id', 'word', 'word_type', name='uq_project_watched_words_project_word_type'),
    )
    op.create_index(
        'idx_project_watched_words_project_type',
        'project_watched_words',
        ['project_id', 'word_type'],
    )


def downgrade() -> None:
    op.drop_index('idx_project_watched_words_project_type', table_name='project_watched_words')
    op.drop_table('project_watched_words')

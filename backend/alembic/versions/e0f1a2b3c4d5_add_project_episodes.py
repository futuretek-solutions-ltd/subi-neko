"""add project_episodes table and files.episode_number

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_episodes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('episode_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('title_native', sa.Text(), nullable=True),
        sa.Column('air_date', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'episode_number', name='uq_project_episodes_project_number'),
    )
    op.create_index('idx_project_episodes_project', 'project_episodes', ['project_id'])

    op.add_column('files', sa.Column('episode_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('files', 'episode_number')
    op.drop_index('idx_project_episodes_project', table_name='project_episodes')
    op.drop_table('project_episodes')

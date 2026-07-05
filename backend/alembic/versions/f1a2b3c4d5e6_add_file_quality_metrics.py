"""add file_quality_metrics table

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e0f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'file_quality_metrics',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('prompt_version', sa.Text(), nullable=True),
        sa.Column('events_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('events_user_edited', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('events_approved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('edit_distance_norm', sa.Float(), nullable=True),
        sa.Column('polish_edit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('qa_blockers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('qa_warnings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('qa_info', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mean_confidence', sa.Float(), nullable=True),
        sa.Column('mean_confidence_edited', sa.Float(), nullable=True),
        sa.Column('llm_cost_usd', sa.Float(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('file_id', name='uq_file_quality_metrics_file'),
    )
    op.create_index('idx_file_quality_metrics_project', 'file_quality_metrics', ['project_id'])


def downgrade() -> None:
    op.drop_index('idx_file_quality_metrics_project', table_name='file_quality_metrics')
    op.drop_table('file_quality_metrics')

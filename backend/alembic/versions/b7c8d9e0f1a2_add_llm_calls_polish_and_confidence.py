"""add llm_calls table, polish/prompt-version chunk columns, per-line confidence

Also migrates chunk statuses from the removed review stages
(rules_reviewed / grammar_reviewed / languagetool_reviewed / llm_reviewed)
back to 'validated' so in-flight chunks re-enter the pipeline at the new
polish stage.

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_calls',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('file_id', sa.Integer(), nullable=True),
        sa.Column('subtitle_chunk_id', sa.Integer(), nullable=True),
        sa.Column('task', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('response_mode', sa.Text(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_llm_calls_project', 'llm_calls', ['project_id'])
    op.create_index('idx_llm_calls_file', 'llm_calls', ['file_id'])

    op.add_column('subtitle_chunks', sa.Column('polish_attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('subtitle_chunks', sa.Column('prompt_version', sa.Text(), nullable=True))

    op.add_column('subtitle_events', sa.Column('translation_confidence', sa.Float(), nullable=True))

    # Chunks stranded in removed review-stage statuses resume at the polish stage.
    op.execute(
        "UPDATE subtitle_chunks SET status = 'validated' "
        "WHERE status IN ('rules_reviewed', 'grammar_reviewed', 'languagetool_reviewed', 'llm_reviewed')"
    )


def downgrade() -> None:
    op.drop_column('subtitle_events', 'translation_confidence')

    op.drop_column('subtitle_chunks', 'prompt_version')
    op.drop_column('subtitle_chunks', 'polish_attempt_count')

    op.drop_index('idx_llm_calls_file', table_name='llm_calls')
    op.drop_index('idx_llm_calls_project', table_name='llm_calls')
    op.drop_table('llm_calls')

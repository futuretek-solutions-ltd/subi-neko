"""post-refactor audit fixes

- Drop the dead LLM_REVIEW_ALWAYS / LLM_REVIEW_FLAGGED_ONLY options:
  review_chunk_final has been deterministic (no LLM) since the workflow
  rework, so the rows only mislead the operator into believing an LLM
  review layer is active.
- file_quality_metrics.polish_churn_norm: mean normalized Levenshtein over
  the polish pass's before/after pairs. edit_distance_norm keeps measuring
  human corrections only (polish keeps original_ai_translated_text in sync
  with its output), so pipeline churn needs its own column.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM options WHERE name IN ('LLM_REVIEW_ALWAYS', 'LLM_REVIEW_FLAGGED_ONLY')"
    )
    op.add_column(
        'file_quality_metrics',
        sa.Column('polish_churn_norm', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('file_quality_metrics') as batch:
        batch.drop_column('polish_churn_norm')
    # The deleted option rows are not restored — they were dead configuration.

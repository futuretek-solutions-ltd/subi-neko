"""gated translation workflow: context approval + per-file translate

- projects.context_approved_at: explicit user approval of the translation
  context (gate 1). Projects already past discovery are grandfathered as
  approved — they translated under the old automatic regime and freezing
  them mid-flight would only wedge in-progress jobs.
- files.translation_requested_at: per-file Translate action (gate 2).
  In-flight files are grandfathered as requested; files still in ready
  (or parked pre-translation) stay unrequested and wait for the user.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('context_approved_at', sa.Text(), nullable=True))
    op.add_column('files', sa.Column('translation_requested_at', sa.Text(), nullable=True))

    # Grandfather projects that already started translating under the old
    # fully-automatic workflow.
    op.execute(
        "UPDATE projects SET context_approved_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') "
        "WHERE status IN ('processing', 'review_required', 'completed')"
    )

    # Grandfather files already past the translation-start point so they keep
    # flowing; ready/pre-translation files stay NULL → await a Translate click.
    op.execute(
        "UPDATE files SET translation_requested_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') "
        "WHERE status IN ('processing', 'review_required', 'muxing', 'completed') "
        "   OR (status = 'waiting' AND blocking_reason IN "
        "       ('translation_failed', 'validation_failed', 'mux_failed', 'user_review_required'))"
    )


def downgrade() -> None:
    op.execute("UPDATE projects SET status = 'discovering' WHERE status = 'context_review'")
    with op.batch_alter_table('files') as batch:
        batch.drop_column('translation_requested_at')
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('context_approved_at')

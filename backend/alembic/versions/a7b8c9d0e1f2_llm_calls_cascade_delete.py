"""llm_calls: cascade-delete with project/file

llm_calls.project_id/file_id had no FK at all, unlike every other
project/file-scoped table — deleting (or re-importing) a project left its
llm_calls rows orphaned in the table forever. Because SQLite ids get reused
after a project is deleted, those orphaned rows can silently attach
themselves to a brand new project/file with the same id, inflating
compute_file_metrics' cost/token totals with unrelated historical usage.

Orphaned rows (no matching project) are purged before the constraint is
added, since SQLite would otherwise refuse to enable the FK on data that
already violates it.

Revision ID: a7b8c9d0e1f2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f2'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM llm_calls WHERE project_id IS NOT NULL "
        "AND project_id NOT IN (SELECT id FROM projects)"
    )
    op.execute(
        "DELETE FROM llm_calls WHERE file_id IS NOT NULL "
        "AND file_id NOT IN (SELECT id FROM files)"
    )
    with op.batch_alter_table('llm_calls') as batch:
        batch.create_foreign_key(
            'fk_llm_calls_project', 'projects', ['project_id'], ['id'], ondelete='CASCADE',
        )
        batch.create_foreign_key(
            'fk_llm_calls_file', 'files', ['file_id'], ['id'], ondelete='CASCADE',
        )


def downgrade() -> None:
    with op.batch_alter_table('llm_calls') as batch:
        batch.drop_constraint('fk_llm_calls_file', type_='foreignkey')
        batch.drop_constraint('fk_llm_calls_project', type_='foreignkey')

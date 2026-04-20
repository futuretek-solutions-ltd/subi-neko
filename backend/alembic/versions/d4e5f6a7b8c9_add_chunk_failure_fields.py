"""add chunk failure tracking fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('subtitle_chunks', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('subtitle_chunks', sa.Column('repair_attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('subtitle_chunks', sa.Column('last_error_code', sa.Text(), nullable=True))
    op.add_column('subtitle_chunks', sa.Column('last_error_message', sa.Text(), nullable=True))
    op.add_column('subtitle_chunks', sa.Column('failed_job_type', sa.Text(), nullable=True))

    # Migrate old status to new name
    op.execute(
        "UPDATE subtitle_chunks SET status = 'validate_trans_failed' WHERE status = 'failed_validation'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE subtitle_chunks SET status = 'failed_validation' WHERE status = 'validate_trans_failed'"
    )
    op.drop_column('subtitle_chunks', 'failed_job_type')
    op.drop_column('subtitle_chunks', 'last_error_message')
    op.drop_column('subtitle_chunks', 'last_error_code')
    op.drop_column('subtitle_chunks', 'repair_attempt_count')
    op.drop_column('subtitle_chunks', 'retry_count')

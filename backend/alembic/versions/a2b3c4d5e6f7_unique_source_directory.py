"""unique source_directory on projects

Revision ID: a2b3c4d5e6f7
Revises: 1c33a815f107
Create Date: 2026-04-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = '1c33a815f107'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_projects_source_directory', ['source_directory'])


def downgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_constraint('uq_projects_source_directory', type_='unique')

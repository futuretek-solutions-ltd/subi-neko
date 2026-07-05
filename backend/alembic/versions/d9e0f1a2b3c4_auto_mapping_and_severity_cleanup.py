"""auto-mapping (N:1 speaker→character) + severity cleanup + gate removal

- project_speakers absorbs the mapping: character_id + confidence/origin/
  rationale + line_count/sample_lines/is_extra; data copied from the M:N
  speaker_character_mappings table (first mapping wins, extras preserved in
  match_rationale), then the M:N table is dropped.
- qa_items.severity collapses to blocker|warning|info.
- The manual mapping gate is removed: projects stuck in waiting_for_mapping
  resume processing; speaker_mapping_status values are remapped so existing
  projects flow through the new automatic inference; files parked on
  project_mapping_required go back to discovering.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'd9e0f1a2b3c4'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- project_speakers: absorb the mapping -----------------------------
    with op.batch_alter_table('project_speakers') as batch:
        batch.add_column(sa.Column('character_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('match_confidence', sa.Float(), nullable=True))
        batch.add_column(sa.Column('match_origin', sa.Text(), nullable=True))
        batch.add_column(sa.Column('match_rationale', sa.Text(), nullable=True))
        batch.add_column(sa.Column('line_count', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('sample_lines_json', sa.Text(), nullable=True))
        batch.add_column(sa.Column('is_extra', sa.Integer(), nullable=False, server_default='0'))
        batch.create_foreign_key(
            'fk_project_speakers_character', 'project_characters',
            ['character_id'], ['id'], ondelete='SET NULL',
        )

    op.execute("""
        UPDATE project_speakers SET
            character_id = (
                SELECT MIN(m.character_id) FROM speaker_character_mappings m
                WHERE m.project_speaker_id = project_speakers.id
            ),
            match_origin = 'manual',
            match_confidence = 1.0
        WHERE EXISTS (
            SELECT 1 FROM speaker_character_mappings m
            WHERE m.project_speaker_id = project_speakers.id
        )
    """)
    op.execute("""
        UPDATE project_speakers SET match_rationale =
            'migrated from multi-mapping; was also mapped to character ids: ' || (
                SELECT GROUP_CONCAT(m.character_id) FROM speaker_character_mappings m
                WHERE m.project_speaker_id = project_speakers.id
                  AND m.character_id != project_speakers.character_id
            )
        WHERE (
            SELECT COUNT(*) FROM speaker_character_mappings m
            WHERE m.project_speaker_id = project_speakers.id
        ) > 1
    """)

    op.drop_table('speaker_character_mappings')

    # --- qa_items: one severity scale --------------------------------------
    op.execute("UPDATE qa_items SET severity = 'blocker' WHERE severity IN ('critical', 'error', 'high')")
    op.execute("UPDATE qa_items SET severity = 'warning' WHERE severity = 'medium'")
    op.execute("UPDATE qa_items SET severity = 'info' WHERE severity = 'low'")

    # --- remove the manual mapping gate -------------------------------------
    op.execute("UPDATE projects SET status = 'processing' WHERE status = 'waiting_for_mapping'")
    op.execute("UPDATE projects SET speaker_mapping_status = 'complete' "
               "WHERE speaker_mapping_status IN ('mapping_complete', 'no_speakers')")
    op.execute("UPDATE projects SET speaker_mapping_status = 'aggregated' "
               "WHERE speaker_mapping_status = 'mapping_required'")
    op.execute("UPDATE files SET status = 'discovering', blocking_reason = NULL "
               "WHERE status = 'waiting' AND blocking_reason = 'project_mapping_required'")


def downgrade() -> None:
    op.create_table(
        'speaker_character_mappings',
        sa.Column('project_speaker_id', sa.Integer(),
                  sa.ForeignKey('project_speakers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('character_id', sa.Integer(),
                  sa.ForeignKey('project_characters.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_speaker_character_mappings_character',
                    'speaker_character_mappings', ['character_id'])
    op.execute("""
        INSERT INTO speaker_character_mappings (project_speaker_id, character_id)
        SELECT id, character_id FROM project_speakers WHERE character_id IS NOT NULL
    """)

    with op.batch_alter_table('project_speakers') as batch:
        batch.drop_constraint('fk_project_speakers_character', type_='foreignkey')
        batch.drop_column('is_extra')
        batch.drop_column('sample_lines_json')
        batch.drop_column('line_count')
        batch.drop_column('match_rationale')
        batch.drop_column('match_origin')
        batch.drop_column('match_confidence')
        batch.drop_column('character_id')

"""add consistency layer: glossary, style bible, character styles,
address pairs, file analyses, translation memory

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'project_glossary_terms',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_term', sa.Text(), nullable=False),
        sa.Column('target_term', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False, server_default='other'),
        sa.Column('gender', sa.Text(), nullable=True),
        sa.Column('vocative', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('origin', sa.Text(), nullable=False, server_default='llm'),
        sa.Column('locked', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('occurrence_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'source_term', 'category',
                            name='uq_project_glossary_terms_project_source_category'),
    )
    op.create_index('idx_project_glossary_terms_project', 'project_glossary_terms', ['project_id'])

    op.create_table(
        'project_style_bibles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tone_summary', sa.Text(), nullable=True),
        sa.Column('register_notes', sa.Text(), nullable=True),
        sa.Column('honorific_policy', sa.Text(), nullable=True),
        sa.Column('generated_from_file_id', sa.Integer(), nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('is_user_edited', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'version', name='uq_project_style_bibles_project_version'),
    )
    op.create_index('idx_project_style_bibles_project', 'project_style_bibles', ['project_id'])

    op.create_table(
        'project_character_styles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_character_id', sa.Integer(),
                  sa.ForeignKey('project_characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('voice_note', sa.Text(), nullable=True),
        sa.Column('register', sa.Text(), nullable=True),
        sa.Column('origin', sa.Text(), nullable=False, server_default='llm'),
        sa.Column('locked', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_character_id', name='uq_project_character_styles_character'),
    )

    op.create_table(
        'project_address_pairs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('speaker_name', sa.Text(), nullable=False),
        sa.Column('addressee_name', sa.Text(), nullable=False),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('origin', sa.Text(), nullable=False, server_default='llm'),
        sa.Column('locked', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'speaker_name', 'addressee_name',
                            name='uq_project_address_pairs_project_speaker_addressee'),
    )
    op.create_index('idx_project_address_pairs_project', 'project_address_pairs', ['project_id'])

    op.create_table(
        'file_analyses',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('synopsis', sa.Text(), nullable=True),
        sa.Column('scenes_json', sa.Text(), nullable=True),
        sa.Column('tricky_lines_json', sa.Text(), nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('file_id', name='uq_file_analyses_file'),
    )

    op.create_table(
        'translation_memory',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_hash', sa.Text(), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('target_text', sa.Text(), nullable=False),
        sa.Column('content_type', sa.Text(), nullable=False, server_default='dialogue'),
        sa.Column('origin', sa.Text(), nullable=False, server_default='ai'),
        sa.Column('src_file_id', sa.Integer(), nullable=True),
        sa.Column('src_line_index', sa.Integer(), nullable=True),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'source_hash', name='uq_translation_memory_project_hash'),
    )
    op.create_index('idx_translation_memory_project_hash', 'translation_memory',
                    ['project_id', 'source_hash'])


def downgrade() -> None:
    op.drop_index('idx_translation_memory_project_hash', table_name='translation_memory')
    op.drop_table('translation_memory')
    op.drop_table('file_analyses')
    op.drop_index('idx_project_address_pairs_project', table_name='project_address_pairs')
    op.drop_table('project_address_pairs')
    op.drop_table('project_character_styles')
    op.drop_index('idx_project_style_bibles_project', table_name='project_style_bibles')
    op.drop_table('project_style_bibles')
    op.drop_index('idx_project_glossary_terms_project', table_name='project_glossary_terms')
    op.drop_table('project_glossary_terms')

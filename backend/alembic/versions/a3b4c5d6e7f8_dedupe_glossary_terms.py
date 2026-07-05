"""remove cross-category glossary duplicates

The LLM re-suggested already-seeded terms under a different category
("Aria" name + "Aria" other) because the insert dedupe key included the
category. Keep the preferred row per (project, source term): user-edited
rows first, then category 'name', then the oldest; delete the unlocked,
non-manual rest. The code-side dedupe is now source-term-only.

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-07-04
"""
from alembic import op

revision = 'a3b4c5d6e7f8'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM project_glossary_terms
        WHERE locked = 0 AND origin != 'manual'
        AND EXISTS (
            SELECT 1 FROM project_glossary_terms g2
            WHERE g2.project_id = project_glossary_terms.project_id
              AND lower(g2.source_term) = lower(project_glossary_terms.source_term)
              AND g2.id != project_glossary_terms.id
              AND (
                (CASE WHEN g2.locked = 1 OR g2.origin = 'manual' THEN 0
                      WHEN g2.category = 'name' THEN 1 ELSE 2 END)
                < (CASE WHEN project_glossary_terms.category = 'name' THEN 1 ELSE 2 END)
                OR (
                  (CASE WHEN g2.locked = 1 OR g2.origin = 'manual' THEN 0
                        WHEN g2.category = 'name' THEN 1 ELSE 2 END)
                  = (CASE WHEN project_glossary_terms.category = 'name' THEN 1 ELSE 2 END)
                  AND g2.id < project_glossary_terms.id
                )
              )
        )
    """)


def downgrade() -> None:
    pass  # data cleanup — not reversible

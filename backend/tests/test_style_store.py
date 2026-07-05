from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.db.models import Project, ProjectGlossaryTerm
from app.jobs.handlers.style_store import insert_new_glossary_terms
from app.llm.schemas import GlossaryTermOut


def _now() -> str:
    return datetime.utcnow().isoformat()


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _make_project(session) -> int:
    project = Project(
        name="P", source_directory="p", anime_provider="anidb", anime_external_id="1",
        created_at=_now(), updated_at=_now(),
    )
    session.add(project)
    session.flush()
    return project.id


def test_glossary_dedupe_is_source_term_only(session_factory):
    """A term seeded under one category must not be re-inserted by the LLM
    under a different one ('Aria' name + 'Aria' other duplicates)."""
    with session_factory() as session:
        project_id = _make_project(session)

        insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Aria", category="name", gender="female"),
        ], "metadata", _now())
        session.commit()

        inserted = insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Aria", category="other"),
            GlossaryTermOut(source="aria", target="Aria", category="catchphrase"),
            GlossaryTermOut(source="Dragon Slash", target="Dračí sek", category="technique"),
        ], "llm", _now())
        session.commit()

        assert inserted == 1  # only Dragon Slash is new
        rows = list(session.scalars(select(ProjectGlossaryTerm)))
        assert sorted(r.source_term for r in rows) == ["Aria", "Dragon Slash"]
        aria = next(r for r in rows if r.source_term == "Aria")
        assert aria.category == "name"  # the seeded row survived untouched


def test_llm_fills_missing_fields_on_metadata_seeded_terms(session_factory):
    """Metadata-seeded names start without vocative/note; a later LLM
    suggestion for the same source term fills exactly the empty fields."""
    with session_factory() as session:
        project_id = _make_project(session)

        insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Aria", category="name", gender="female"),
        ], "metadata", _now())
        session.commit()

        inserted = insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Árie", category="name",
                            gender="male", vocative="Ario", note="Hlavní hrdinka"),
        ], "llm", _now())
        session.commit()

        assert inserted == 0
        aria = session.scalar(
            select(ProjectGlossaryTerm).where(ProjectGlossaryTerm.source_term == "Aria"))
        assert aria.target_term == "Aria"       # existing rendering never replaced
        assert aria.origin == "metadata"        # origin preserved
        assert aria.gender == "female"          # non-empty field never overwritten
        assert aria.vocative == "Ario"          # empty field filled
        assert aria.note == "Hlavní hrdinka"    # empty field filled


def test_llm_never_touches_locked_terms(session_factory):
    with session_factory() as session:
        project_id = _make_project(session)

        insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Aria", category="name"),
        ], "manual", _now())
        term = session.scalar(select(ProjectGlossaryTerm))
        term.locked = 1
        session.commit()

        insert_new_glossary_terms(session, project_id, [
            GlossaryTermOut(source="Aria", target="Árie", category="name",
                            vocative="Ario", note="poznámka"),
        ], "llm", _now())
        session.commit()

        aria = session.scalar(select(ProjectGlossaryTerm))
        assert aria.vocative is None
        assert aria.note is None

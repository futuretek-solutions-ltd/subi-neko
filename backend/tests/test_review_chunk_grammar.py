from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.db.models import File, Project, QaItem, SubtitleChunk, SubtitleEvent
from app.grammar.providers import GrammarCheckResult
from app.jobs.handlers import review_chunk_grammar as grammar_handler


def _now() -> str:
    return datetime.utcnow().isoformat()


@pytest.fixture
def sync_session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(grammar_handler, "SyncSessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _ctx(provider: str = "korektor", base_url: str = "http://grammar:8010"):
    return SimpleNamespace(
        import_root=Path("."),
        output_root=Path("."),
        options=SimpleNamespace(
            grammar_provider=provider,
            grammar_provider_base_url=base_url,
            target_lang_code="cs",
        ),
    )


def _create_chunk_graph(factory, *, translated_texts: list[str]) -> tuple[int, int]:
    with factory() as session:
        project = Project(
            name="P",
            source_directory="p",
            anime_provider="test",
            anime_external_id="p",
            status="processing",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(project)
        session.flush()
        file = File(
            project_id=project.id,
            filename="f.mkv",
            relative_path="f.mkv",
            status="processing",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(file)
        session.flush()
        chunk = SubtitleChunk(
            file_id=file.id,
            chunk_index=0,
            translate_from_line=0,
            translate_to_line=max(0, len(translated_texts) - 1),
            status="rules_reviewed",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(chunk)
        for i, translated_text in enumerate(translated_texts):
            session.add(SubtitleEvent(
                file_id=file.id,
                line_index=i,
                event_type="dialogue",
                layer=0,
                start_ms=0,
                end_ms=1000,
                style="Default",
                source_text=f"Source {i}",
                translated_text=translated_text,
                translation_status="translated",
                created_at=_now(),
                updated_at=_now(),
            ))
        session.commit()
        return file.id, chunk.chunk_index


class FailingProvider:
    base_url = "http://grammar:8010"
    endpoint_url = "http://grammar:8010/check"

    async def check(self, text: str, language: str) -> GrammarCheckResult:
        raise httpx.ConnectError("connection refused")


class PassingProvider:
    base_url = "http://grammar:8010"
    endpoint_url = "http://grammar:8010/check"

    async def check(self, text: str, language: str) -> GrammarCheckResult:
        return GrammarCheckResult(text=text, corrected_text=None, matches=[])


def test_review_chunk_grammar_fails_on_provider_connection_error(sync_session_factory, monkeypatch):
    file_id, chunk_index = _create_chunk_graph(sync_session_factory, translated_texts=["Ahoj"])
    monkeypatch.setattr(grammar_handler, "create_grammar_provider", lambda provider, base_url: FailingProvider())

    result = grammar_handler.review_chunk_grammar(
        {"file_id": file_id, "chunk_index": chunk_index},
        _ctx(),
        lambda pct, msg: None,
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "GRAMMAR_PROVIDER_ERROR"
    assert "korektor" in result["error_message"]
    assert "http://grammar:8010" in result["error_message"]
    assert "connection refused" in result["error_message"]

    with sync_session_factory() as session:
        chunk = session.scalar(select(SubtitleChunk))
        assert chunk.status == "rules_reviewed"
        assert session.scalar(select(QaItem)) is None


def test_review_chunk_grammar_succeeds_and_sets_reviewed(sync_session_factory, monkeypatch):
    file_id, chunk_index = _create_chunk_graph(sync_session_factory, translated_texts=["Ahoj"])
    monkeypatch.setattr(grammar_handler, "create_grammar_provider", lambda provider, base_url: PassingProvider())

    result = grammar_handler.review_chunk_grammar(
        {"file_id": file_id, "chunk_index": chunk_index},
        _ctx(),
        lambda pct, msg: None,
    )

    assert result["status"] == "succeeded"
    assert result["result"]["events_checked"] == 1

    with sync_session_factory() as session:
        chunk = session.scalar(select(SubtitleChunk))
        assert chunk.status == "grammar_reviewed"


def test_review_chunk_grammar_succeeds_with_zero_eligible_events(sync_session_factory, monkeypatch):
    file_id, chunk_index = _create_chunk_graph(sync_session_factory, translated_texts=[""])
    monkeypatch.setattr(grammar_handler, "create_grammar_provider", lambda provider, base_url: FailingProvider())

    result = grammar_handler.review_chunk_grammar(
        {"file_id": file_id, "chunk_index": chunk_index},
        _ctx(),
        lambda pct, msg: None,
    )

    assert result["status"] == "succeeded"
    assert result["result"]["events_checked"] == 1

    with sync_session_factory() as session:
        chunk = session.scalar(select(SubtitleChunk))
        assert chunk.status == "grammar_reviewed"

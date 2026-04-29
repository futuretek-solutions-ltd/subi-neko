from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.db.models import File, Project, SubtitleChunk, SubtitleEvent
from app.db.options import AppOptions
from app.jobs.context import JobContext
from app.jobs.handlers import plan_translation_chunks as planner


def _progress(_value: float, _message: str) -> None:
    pass


def test_effective_chunk_size_eliminates_small_tail_chunk():
    assert planner._effective_chunk_size(total_lines=167, configured_chunk_size=80) == 84


def test_effective_chunk_size_keeps_tail_at_ten_percent():
    assert planner._effective_chunk_size(total_lines=168, configured_chunk_size=80) == 80


def test_plan_translation_chunks_redistributes_small_tail(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(planner, "SyncSessionLocal", factory)

    now = datetime.utcnow().isoformat()
    with factory() as session:
        project = Project(
            name="Test",
            source_directory="test",
            anime_provider="test",
            anime_external_id="test-1",
            speaker_mapping_status="mapping_complete",
            status="processing",
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        session.flush()

        file = File(
            project_id=project.id,
            filename="test.mkv",
            relative_path="test.mkv",
            status="ready",
            created_at=now,
            updated_at=now,
        )
        session.add(file)
        session.flush()

        session.add_all([
            SubtitleEvent(
                file_id=file.id,
                line_index=i,
                event_type="dialogue",
                layer=0,
                start_ms=i * 1000,
                end_ms=i * 1000 + 500,
                style="Default",
                source_text=f"Line {i}",
                translation_status="pending",
                created_at=now,
                updated_at=now,
            )
            for i in range(167)
        ])
        session.commit()
        file_id = file.id

    ctx = JobContext(
        import_root=Path("."),
        output_root=Path("."),
        options=AppOptions(chunk_size=80, prepend_context_size=5),
    )

    result = planner.plan_translation_chunks({"file_id": file_id}, ctx, _progress)

    assert result["status"] == "succeeded"
    assert result["result"] == {"chunks_created": 2}

    with factory() as session:
        chunks = list(session.scalars(
            select(SubtitleChunk).order_by(SubtitleChunk.chunk_index)
        ))

    assert [(c.translate_from_line, c.translate_to_line) for c in chunks] == [
        (0, 83),
        (84, 166),
    ]

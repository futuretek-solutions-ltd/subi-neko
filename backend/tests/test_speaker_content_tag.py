"""Endpoint tests for speaker content tags (sign/karaoke/song).

Uses the same in-memory async SQLite + monkeypatched AsyncSessionLocal
pattern as test_orchestrator.py.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.db.models import Project, ProjectCharacter, ProjectSpeaker


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.api.routes.projects.AsyncSessionLocal", session_factory)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _create_project(session) -> Project:
    now = datetime.utcnow().isoformat()
    p = Project(
        name="Test", source_directory="test", anime_provider="test",
        anime_external_id="test-1", status="processing",
        speaker_mapping_status="complete", created_at=now, updated_at=now,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _create_character(session, project_id: int, name: str = "Alice") -> ProjectCharacter:
    now = datetime.utcnow().isoformat()
    c = ProjectCharacter(project_id=project_id, name=name, created_at=now, updated_at=now)
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


async def _create_speaker(
    session, project_id: int, name: str = "OP-lyrics",
    character_id: int | None = None, is_extra: int = 0,
    content_tag: str | None = None,
) -> ProjectSpeaker:
    now = datetime.utcnow().isoformat()
    s = ProjectSpeaker(
        project_id=project_id, name=name, character_id=character_id,
        is_extra=is_extra, content_tag=content_tag,
        created_at=now, updated_at=now,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


class TestSpeakerContentTag:
    @pytest.mark.asyncio
    async def test_setting_tag_clears_mapping_and_sets_manual_origin(self, db_session):
        from app.api.routes.projects import SpeakerUpdateIn, update_project_speaker

        project = await _create_project(db_session)
        character = await _create_character(db_session, project.id)
        speaker = await _create_speaker(db_session, project.id, character_id=character.id)

        result = await update_project_speaker(
            project.id, speaker.id, SpeakerUpdateIn(content_tag="karaoke"))

        assert result.speaker.content_tag == "karaoke"
        assert result.speaker.character_id is None
        assert result.speaker.is_extra is False
        assert result.speaker.match_origin == "manual"

    @pytest.mark.asyncio
    async def test_assigning_character_clears_tag(self, db_session):
        from app.api.routes.projects import SpeakerUpdateIn, update_project_speaker

        project = await _create_project(db_session)
        character = await _create_character(db_session, project.id)
        speaker = await _create_speaker(db_session, project.id, content_tag="sign")

        result = await update_project_speaker(
            project.id, speaker.id, SpeakerUpdateIn(character_id=character.id))

        assert result.speaker.character_id == character.id
        assert result.speaker.content_tag is None

    @pytest.mark.asyncio
    async def test_marking_extra_clears_tag(self, db_session):
        from app.api.routes.projects import SpeakerUpdateIn, update_project_speaker

        project = await _create_project(db_session)
        speaker = await _create_speaker(db_session, project.id, content_tag="song")

        result = await update_project_speaker(
            project.id, speaker.id, SpeakerUpdateIn(is_extra=True))

        assert result.speaker.is_extra is True
        assert result.speaker.content_tag is None

    @pytest.mark.asyncio
    async def test_explicit_null_untags(self, db_session):
        from app.api.routes.projects import SpeakerUpdateIn, update_project_speaker

        project = await _create_project(db_session)
        speaker = await _create_speaker(db_session, project.id, content_tag="sign")

        result = await update_project_speaker(
            project.id, speaker.id, SpeakerUpdateIn(content_tag=None))

        assert result.speaker.content_tag is None

    @pytest.mark.asyncio
    async def test_tag_survives_unrelated_gender_update(self, db_session):
        from app.api.routes.projects import SpeakerUpdateIn, update_project_speaker

        project = await _create_project(db_session)
        speaker = await _create_speaker(db_session, project.id, content_tag="karaoke")

        result = await update_project_speaker(
            project.id, speaker.id, SpeakerUpdateIn(gender="female"))

        assert result.speaker.content_tag == "karaoke"
        assert result.speaker.gender == "female"

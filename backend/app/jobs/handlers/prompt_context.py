from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import ProjectCharacter, ProjectSpeaker, SpeakerCharacterMapping


def load_prompt_characters(session: Session, project_id: int) -> list[ProjectCharacter]:
    return list(session.scalars(
        select(ProjectCharacter).where(ProjectCharacter.project_id == project_id)
    ).all())


def load_unmapped_gendered_speakers(session: Session, project_id: int) -> list[ProjectSpeaker]:
    speakers = list(session.scalars(
        select(ProjectSpeaker)
        .where(ProjectSpeaker.project_id == project_id)
        .where(ProjectSpeaker.gender.isnot(None))
        .options(selectinload(ProjectSpeaker.character_mappings))
        .order_by(ProjectSpeaker.name)
    ).all())
    return [
        speaker
        for speaker in speakers
        if speaker.gender and not any(mapping.character_id for mapping in speaker.character_mappings)
    ]


def build_character_block(characters: list[ProjectCharacter]) -> str:
    lines = []
    for character in characters:
        extras = [(key, value) for key, value in [
            ("gender", character.gender),
            ("social_position", character.social_position),
            ("note", character.note),
        ] if value and value.strip()]
        if not extras:
            continue
        parts = [character.name] + [f"{key}: {value}" for key, value in extras]
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def build_unmapped_speaker_block(speakers: list[ProjectSpeaker]) -> str:
    lines = []
    for speaker in speakers:
        if speaker.gender and speaker.gender.strip():
            lines.append(f"- {speaker.name}, gender: {speaker.gender}")
    return "\n".join(lines)

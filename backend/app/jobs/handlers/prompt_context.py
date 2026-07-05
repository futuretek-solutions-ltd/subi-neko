from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    File,
    FileAnalysis,
    ProjectAddressPair,
    ProjectCharacter,
    ProjectCharacterStyle,
    ProjectEpisode,
    ProjectGlossaryTerm,
    ProjectSpeaker,
    ProjectStyleBible,
)
from app.subs.tag_masking import plain_text

# AniDB character_type values that denote non-speaking "characters"
# (organizations, vessels/mecha, etc.) — not useful as speaker candidates.
_NON_SPEAKING_CHARACTER_TYPES = {"organization", "vessel"}

_DESCRIPTION_MAX_LEN = 200


def load_prompt_characters(session: Session, project_id: int) -> list[ProjectCharacter]:
    characters = list(session.scalars(
        select(ProjectCharacter).where(ProjectCharacter.project_id == project_id)
    ).all())
    return [
        c for c in characters
        if not (c.character_type and c.character_type.strip().lower() in _NON_SPEAKING_CHARACTER_TYPES)
    ]


def load_unmapped_gendered_speakers(session: Session, project_id: int) -> list[ProjectSpeaker]:
    speakers = list(session.scalars(
        select(ProjectSpeaker)
        .where(ProjectSpeaker.project_id == project_id)
        .where(ProjectSpeaker.gender.isnot(None))
        .where(ProjectSpeaker.character_id.is_(None))
        .order_by(ProjectSpeaker.name)
    ).all())
    return [speaker for speaker in speakers if speaker.gender]


def build_speaker_identity_map(
    session: Session, project_id: int,
) -> dict[str, tuple[str | None, str | None]]:
    """Map raw subtitle speaker name → (display name, gender) for per-line
    prompt annotations. Mapped speakers use their character's name/gender
    (speaker gender wins when set explicitly); unmapped speakers fall back
    to their own name/gender."""
    speakers = list(session.scalars(
        select(ProjectSpeaker)
        .where(ProjectSpeaker.project_id == project_id)
        .options(selectinload(ProjectSpeaker.character))
    ).all())

    identities: dict[str, tuple[str | None, str | None]] = {}
    for speaker in speakers:
        character = speaker.character
        if character is not None:
            name = character.name or speaker.name
            gender = speaker.gender or character.gender
        else:
            name = speaker.name
            gender = speaker.gender
        identities[speaker.name] = (name, gender)
    return identities


def _truncated_description(description: str | None) -> str | None:
    if not description:
        return None
    stripped = description.strip()
    if not stripped:
        return None
    if len(stripped) <= _DESCRIPTION_MAX_LEN:
        return stripped
    return stripped[:_DESCRIPTION_MAX_LEN].rstrip() + "…"


def build_character_block(characters: list[ProjectCharacter]) -> str:
    lines = []
    for character in characters:
        extras = [(key, value) for key, value in [
            ("gender", character.gender),
            ("social_position", character.social_position),
            ("personality", _truncated_description(character.description)),
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


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

# Categories that are always injected regardless of chunk content — names
# and places must stay consistent even when only inflected forms appear.
_ALWAYS_INCLUDED_CATEGORIES = {"name", "place"}
_MAX_GLOSSARY_LINES = 80


def load_glossary_terms(session: Session, project_id: int) -> list[ProjectGlossaryTerm]:
    return list(session.scalars(
        select(ProjectGlossaryTerm)
        .where(ProjectGlossaryTerm.project_id == project_id)
        .where(ProjectGlossaryTerm.is_active == 1)
        .order_by(ProjectGlossaryTerm.category, ProjectGlossaryTerm.source_term)
    ).all())


def build_glossary_block(terms: list[ProjectGlossaryTerm], chunk_texts: list[str]) -> str:
    """Names/places always; other categories only when the term occurs in
    the chunk's source text. Capped so a huge glossary can't flood the
    prompt (always-included categories win the budget)."""
    combined = " ".join(plain_text(t) for t in chunk_texts).casefold()

    selected: list[ProjectGlossaryTerm] = []
    for term in terms:
        if term.category in _ALWAYS_INCLUDED_CATEGORIES:
            selected.append(term)
        elif term.source_term.casefold() in combined:
            selected.append(term)

    lines = []
    for term in selected[:_MAX_GLOSSARY_LINES]:
        extras = []
        if term.vocative:
            extras.append(f"vocative: {term.vocative}")
        if term.gender:
            extras.append(f"gender: {term.gender}")
        if term.note:
            extras.append(term.note)
        suffix = f" ({'; '.join(extras)})" if extras else ""
        if term.source_term == term.target_term:
            lines.append(f'- "{term.source_term}" — keep as-is{suffix}')
        else:
            lines.append(f'- "{term.source_term}" => "{term.target_term}"{suffix}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Style bible + character voices + address pairs
# ---------------------------------------------------------------------------

@dataclass
class StyleContext:
    tone_summary: str | None = None
    register_notes: str | None = None
    honorific_policy: str | None = None
    voices: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)  # character name → (voice, register)
    pairs: list[tuple[str, str, str]] = field(default_factory=list)  # (speaker, addressee, mode)

    @property
    def has_content(self) -> bool:
        return bool(self.tone_summary or self.register_notes or self.honorific_policy
                    or self.voices or self.pairs)


def load_style_context(session: Session, project_id: int) -> StyleContext:
    ctx = StyleContext()

    bible = session.scalar(
        select(ProjectStyleBible)
        .where(ProjectStyleBible.project_id == project_id)
        .order_by(ProjectStyleBible.version.desc())
        .limit(1)
    )
    if bible is not None:
        ctx.tone_summary = bible.tone_summary
        ctx.register_notes = bible.register_notes
        ctx.honorific_policy = bible.honorific_policy

    rows = session.execute(
        select(ProjectCharacter.name, ProjectCharacterStyle.voice_note, ProjectCharacterStyle.register)
        .join(ProjectCharacterStyle, ProjectCharacterStyle.project_character_id == ProjectCharacter.id)
        .where(ProjectCharacter.project_id == project_id)
    ).all()
    for name, voice_note, register in rows:
        ctx.voices[name] = (voice_note, register)

    pairs = session.scalars(
        select(ProjectAddressPair).where(ProjectAddressPair.project_id == project_id)
    ).all()
    ctx.pairs = [(p.speaker_name, p.addressee_name, p.mode) for p in pairs]

    return ctx


def build_style_block(
    style: StyleContext,
    raw_speakers_present: set[str],
    identities: dict[str, tuple[str | None, str | None]],
) -> str:
    """Project tone/policy plus voices and address pairs for the speakers
    that actually appear in the chunk."""
    parts: list[str] = []
    if style.tone_summary:
        parts.append(f"Tone: {style.tone_summary}")
    if style.register_notes:
        parts.append(f"Register: {style.register_notes}")
    if style.honorific_policy:
        parts.append(f"Honorifics: {style.honorific_policy}")

    # Character names for the raw speakers present in this chunk.
    present_characters = {
        identities.get(raw, (raw, None))[0]
        for raw in raw_speakers_present if raw
    }
    voice_lines = [
        f"- {name}: {voice or ''}" + (f" (register: {register})" if register else "")
        for name, (voice, register) in sorted(style.voices.items())
        if name in present_characters
    ]
    if voice_lines:
        parts.append("Character voices:\n" + "\n".join(voice_lines))

    present_raw = {s.casefold() for s in raw_speakers_present if s}
    pair_lines = [
        f"- {speaker} addresses {addressee}: {mode}"
        for speaker, addressee, mode in style.pairs
        if speaker.casefold() in present_raw
    ]
    if pair_lines:
        parts.append("Address (T-V) pairs:\n" + "\n".join(pair_lines))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Episode metadata
# ---------------------------------------------------------------------------

def load_episode_context(session: Session, file: File) -> str | None:
    """One-line episode identification ('Episode 12: "Title"') for prompts,
    from the filename-parsed episode number + provider episode metadata."""
    if file.episode_number is None:
        return None
    episode = session.scalar(
        select(ProjectEpisode)
        .where(ProjectEpisode.project_id == file.project_id)
        .where(ProjectEpisode.episode_number == file.episode_number)
    )
    if episode is not None and episode.title:
        return f'Episode {file.episode_number}: "{episode.title}"'
    return f"Episode {file.episode_number}"


# ---------------------------------------------------------------------------
# File analysis (synopsis / scenes / tricky lines)
# ---------------------------------------------------------------------------

@dataclass
class AnalysisContext:
    synopsis: str | None = None
    scenes: list[dict] = field(default_factory=list)        # {from_line,to_line,summary,setting}
    tricky_lines: dict[int, str] = field(default_factory=dict)  # line_index → note


def load_analysis_context(session: Session, file_id: int) -> AnalysisContext | None:
    analysis = session.scalar(
        select(FileAnalysis).where(FileAnalysis.file_id == file_id)
    )
    if analysis is None:
        return None

    ctx = AnalysisContext(synopsis=analysis.synopsis)
    try:
        ctx.scenes = json.loads(analysis.scenes_json or "[]")
    except json.JSONDecodeError:
        ctx.scenes = []
    try:
        ctx.tricky_lines = {
            int(item["i"]): str(item["note"])
            for item in json.loads(analysis.tricky_lines_json or "[]")
            if isinstance(item, dict) and "i" in item and "note" in item
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        ctx.tricky_lines = {}
    return ctx


def build_scene_block(analysis: AnalysisContext, from_line: int, to_line: int) -> str:
    """Episode synopsis plus scene summaries overlapping the chunk range."""
    parts: list[str] = []
    if analysis.synopsis:
        parts.append(f"Episode synopsis: {analysis.synopsis}")

    overlapping = [
        s for s in analysis.scenes
        if isinstance(s, dict)
        and isinstance(s.get("from_line"), int) and isinstance(s.get("to_line"), int)
        and s["from_line"] <= to_line and s["to_line"] >= from_line
    ]
    if overlapping:
        scene_lines = []
        for s in overlapping:
            setting = f" [{s['setting']}]" if s.get("setting") else ""
            scene_lines.append(f"- lines {s['from_line']}-{s['to_line']}{setting}: {s.get('summary', '')}")
        parts.append("Current scenes:\n" + "\n".join(scene_lines))

    return "\n".join(parts)


def build_tricky_notes_block(analysis: AnalysisContext, line_indices: list[int]) -> str:
    lines = [
        f"- line {li}: {analysis.tricky_lines[li]}"
        for li in line_indices if li in analysis.tricky_lines
    ]
    return "\n".join(lines)

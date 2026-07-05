"""Exact-match translation memory.

Populated when a file is accepted for muxing (final, possibly user-edited
translations); consulted by translate_chunk before prompting. Human entries
(user-edited or approved lines) always win over AI entries and are never
downgraded. The big win is OP/ED lyrics and recurring lines, which repeat
verbatim across episodes.

Lookup is by a normalized hash (markup stripped, casefolded, whitespace
collapsed); auto-application additionally requires the RAW source text to
match exactly so stored inline tags can never leak into a differently
formatted line — normalized-only matches are offered as suggestions instead.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SubtitleEvent, TranslationMemoryEntry
from app.subs.tag_masking import plain_text

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def normalize_source(text: str) -> str:
    return _WS_RE.sub(" ", plain_text(text or "").casefold()).strip()


def source_hash(text: str) -> str:
    return hashlib.sha1(normalize_source(text).encode("utf-8")).hexdigest()


@dataclass
class TmMatch:
    target_text: str
    origin: str          # human | ai
    exact_raw: bool      # raw source_text identical → safe to auto-apply
    entry_id: int


def populate_from_file(session: Session, project_id: int, file_id: int, now: str | None = None) -> int:
    """Upsert every translated event of the file into the project TM.
    Human rows (user-edited/approved) are never replaced by AI rows."""
    now = now or datetime.utcnow().isoformat()

    events = list(session.scalars(
        select(SubtitleEvent)
        .where(SubtitleEvent.file_id == file_id)
        .where(SubtitleEvent.event_type == "dialogue")
        .where(SubtitleEvent.translated_text.isnot(None))
        .order_by(SubtitleEvent.line_index)
    ).all())

    existing = {
        row.source_hash: row
        for row in session.scalars(
            select(TranslationMemoryEntry)
            .where(TranslationMemoryEntry.project_id == project_id)
        ).all()
    }

    written = 0
    for event in events:
        if not (event.translated_text or "").strip():
            continue
        if not normalize_source(event.source_text):
            continue
        origin = "human" if (event.is_user_edited or event.is_approved) else "ai"
        digest = source_hash(event.source_text)
        row = existing.get(digest)
        if row is None:
            row = TranslationMemoryEntry(
                project_id=project_id,
                source_hash=digest,
                source_text=event.source_text,
                target_text=event.translated_text,
                content_type=event.content_type or "dialogue",
                origin=origin,
                src_file_id=file_id,
                src_line_index=event.line_index,
                use_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            existing[digest] = row
            written += 1
            continue

        if row.origin == "human" and origin == "ai":
            continue  # never downgrade a human entry
        if row.target_text == event.translated_text and row.origin == origin:
            continue
        row.source_text = event.source_text
        row.target_text = event.translated_text
        row.content_type = event.content_type or "dialogue"
        row.origin = origin
        row.src_file_id = file_id
        row.src_line_index = event.line_index
        row.updated_at = now
        written += 1

    return written


def upsert_event_entry(
    session: Session,
    project_id: int,
    event: SubtitleEvent,
    origin: str,
    now: str | None = None,
) -> bool:
    """Sync one corrected event into the TM (post-acceptance editor edits):
    the human correction is the freshest truth for this source line, so a
    human-origin upsert always overwrites. Returns True when a row changed."""
    if event.event_type != "dialogue":
        return False
    if not (event.translated_text or "").strip():
        return False
    if not normalize_source(event.source_text):
        return False

    now = now or datetime.utcnow().isoformat()
    digest = source_hash(event.source_text)
    row = session.scalar(
        select(TranslationMemoryEntry)
        .where(TranslationMemoryEntry.project_id == project_id)
        .where(TranslationMemoryEntry.source_hash == digest)
    )
    if row is None:
        session.add(TranslationMemoryEntry(
            project_id=project_id,
            source_hash=digest,
            source_text=event.source_text,
            target_text=event.translated_text,
            content_type=event.content_type or "dialogue",
            origin=origin,
            src_file_id=event.file_id,
            src_line_index=event.line_index,
            use_count=0,
            created_at=now,
            updated_at=now,
        ))
        return True

    if row.origin == "human" and origin == "ai":
        return False  # never downgrade a human entry from an AI-valued edit
    if row.target_text == event.translated_text and row.origin == origin:
        return False
    row.source_text = event.source_text
    row.target_text = event.translated_text
    row.content_type = event.content_type or "dialogue"
    row.origin = origin
    row.src_file_id = event.file_id
    row.src_line_index = event.line_index
    row.updated_at = now
    return True


def downgrade_event_entry(
    session: Session,
    project_id: int,
    event: SubtitleEvent,
    now: str | None = None,
) -> bool:
    """The user reverted this event to the AI text: if the TM's human entry
    for that source came from THIS exact event, it no longer represents a
    human correction — refresh its target and demote it to AI origin. Human
    entries owned by another line are left alone. Returns True on change."""
    if not normalize_source(event.source_text):
        return False

    digest = source_hash(event.source_text)
    row = session.scalar(
        select(TranslationMemoryEntry)
        .where(TranslationMemoryEntry.project_id == project_id)
        .where(TranslationMemoryEntry.source_hash == digest)
    )
    if row is None or row.origin != "human":
        return False
    if row.src_file_id != event.file_id or row.src_line_index != event.line_index:
        return False

    row.target_text = event.translated_text
    row.origin = "ai"
    row.updated_at = now or datetime.utcnow().isoformat()
    return True


def lookup(
    session: Session,
    project_id: int,
    source_texts: dict[int, str],
) -> dict[int, TmMatch]:
    """Batch lookup: line_index → TmMatch for every line with a TM hit."""
    hashes = {li: source_hash(text) for li, text in source_texts.items()
              if normalize_source(text)}
    if not hashes:
        return {}

    rows = {
        row.source_hash: row
        for row in session.scalars(
            select(TranslationMemoryEntry)
            .where(TranslationMemoryEntry.project_id == project_id)
            .where(TranslationMemoryEntry.source_hash.in_(set(hashes.values())))
        ).all()
    }

    matches: dict[int, TmMatch] = {}
    for line_index, digest in hashes.items():
        row = rows.get(digest)
        if row is None:
            continue
        matches[line_index] = TmMatch(
            target_text=row.target_text,
            origin=row.origin,
            exact_raw=(row.source_text == source_texts[line_index]),
            entry_id=row.id,
        )
    return matches


# Fuzzy matching guards: suggestions only kick in above this similarity, and
# the brute-force scan is skipped entirely on unreasonably large TMs.
_FUZZY_SCORE_CUTOFF = 92.0
_FUZZY_MAX_TM_ENTRIES = 20_000
_FUZZY_MIN_LENGTH = 12  # short lines fuzzy-match everything — not useful


def fuzzy_suggest(
    session: Session,
    project_id: int,
    source_texts: dict[int, str],
) -> dict[int, TmMatch]:
    """Near-match TM suggestions for lines WITHOUT an exact hit: line_index →
    TmMatch with exact_raw=False (never auto-applied, shown as [TM] hints).
    Brute-force rapidfuzz over the project TM — per-project TMs are small."""
    from rapidfuzz import fuzz, process

    candidates = {
        li: normalize_source(text)
        for li, text in source_texts.items()
        if len(normalize_source(text)) >= _FUZZY_MIN_LENGTH
    }
    if not candidates:
        return {}

    rows = list(session.scalars(
        select(TranslationMemoryEntry)
        .where(TranslationMemoryEntry.project_id == project_id)
    ).all())
    if not rows or len(rows) > _FUZZY_MAX_TM_ENTRIES:
        return {}

    choices = [normalize_source(row.source_text) for row in rows]

    matches: dict[int, TmMatch] = {}
    for line_index, normalized in candidates.items():
        best = process.extractOne(
            normalized, choices, scorer=fuzz.ratio, score_cutoff=_FUZZY_SCORE_CUTOFF,
        )
        if best is None:
            continue
        _choice, score, index = best
        row = rows[index]
        if score >= 100.0:
            continue  # exact normalized match — the exact lookup owns these
        matches[line_index] = TmMatch(
            target_text=row.target_text,
            origin=row.origin,
            exact_raw=False,
            entry_id=row.id,
        )
    return matches


def record_uses(session: Session, entry_ids: list[int], now: str | None = None) -> None:
    if not entry_ids:
        return
    now = now or datetime.utcnow().isoformat()
    rows = session.scalars(
        select(TranslationMemoryEntry).where(TranslationMemoryEntry.id.in_(entry_ids))
    ).all()
    for row in rows:
        row.use_count = (row.use_count or 0) + 1
        row.updated_at = now

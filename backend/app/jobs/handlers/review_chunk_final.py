"""Deterministic final review — no LLM.

Runs after the polish pass: Czech gender-agreement / T-V mixing flags,
readability (CPS, row length, row count) and untranslated-English detection.

On the first pass, any finding routes the chunk to a targeted polish re-pass
(status "needs_polish") with the findings stored as unresolved QaItems that
polish_chunk turns into explicit fix instructions. After the re-pass the
chunk always advances to "final_reviewed" and whatever findings remain
surface to the reviewer as warnings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.database import SyncSessionLocal
from app.db.models import File, ProjectAddressPair, QaItem, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.handlers.prompt_context import build_speaker_identity_map, load_glossary_terms
from app.jobs.registry import register_job_handler
from app.subs.czech_checks import (
    check_gender_agreement,
    check_readability,
    check_tv_against_pairs,
    check_tv_mixed_in_line,
    check_untranslated_english,
    check_vocative,
)
from app.subs.line_breaking import rebalance_rows
logger = logging.getLogger(__name__)

# qa_types produced here — used to scope deletion of stale findings and to
# select the lines for the targeted polish re-pass.
FINAL_REVIEW_QA_TYPES = {
    "gender_agreement",
    "tv_address_mixed",
    "tv_address_mismatch",
    "vocative_missing",
    "high_cps",
    "long_row",
    "too_many_rows",
    "untranslated_english",
    "low_confidence",
}

# Findings that route the chunk into the targeted polish re-pass.
# low_confidence is triage information for the reviewer, not something a
# blind re-polish can reliably fix.
_STRONG_QA_TYPES = FINAL_REVIEW_QA_TYPES - {"low_confidence"}

# One targeted polish re-pass: first review may send the chunk back, the
# second review always lets it through.
_MAX_POLISH_ATTEMPTS = 2


@register_job_handler("review_chunk_final")
def review_chunk_final(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    chunk_index: int = payload["chunk_index"]
    now = datetime.utcnow().isoformat()

    progress(0.05, "Loading chunk definition")

    with SyncSessionLocal() as session:
        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is None:
            return JobResult(status="failed", result=None,
                             error_code="CHUNK_NOT_FOUND",
                             error_message=f"Chunk {chunk_index} for file {file_id} not found")
        if chunk.status != "polished":
            return JobResult(status="failed", result=None,
                             error_code="CHUNK_NOT_POLISHED",
                             error_message=(
                                 f"Chunk {chunk_index} has status '{chunk.status}'; "
                                 "review_chunk_final requires status 'polished'"
                             ))

        translate_from = chunk.translate_from_line
        translate_to = chunk.translate_to_line
        content_type = chunk.content_type or "dialogue"
        polish_attempts = chunk.polish_attempt_count or 0

        # The checks below are dialogue heuristics; signs, karaoke and song
        # lyrics false-positive on them (refrains, terse on-screen text).
        if content_type != "dialogue":
            chunk.status = "final_reviewed"
            chunk.updated_at = now
            session.commit()
            progress(1.0, f"Skipped for content_type={content_type}")
            return JobResult(status="succeeded",
                             result={"warnings_created": 0, "skipped_content_type": content_type},
                             error_code=None, error_message=None)

        file = session.get(File, file_id)
        identities = build_speaker_identity_map(session, file.project_id) if file else {}

        # Address-pair modes per raw speaker name (for the uniform-mode T-V
        # check) and glossary vocative forms.
        speaker_modes: dict[str, set[str]] = {}
        vocatives: dict[str, str] = {}
        # Established names/honorifics are preserved verbatim by design —
        # they must not count as untranslated-English evidence.
        english_exclude: set[str] = set()
        if file is not None:
            for pair in session.scalars(
                select(ProjectAddressPair)
                .where(ProjectAddressPair.project_id == file.project_id)
            ).all():
                speaker_modes.setdefault(pair.speaker_name, set()).add(pair.mode)
            for term in load_glossary_terms(session, file.project_id):
                if term.category == "name" and term.vocative:
                    vocatives[term.target_term] = term.vocative
                if term.category in ("name", "honorific"):
                    for value in (term.source_term, term.target_term):
                        english_exclude.update((value or "").replace("-", " ").split())

        target_events = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.event_type == "dialogue")
            .where(SubtitleEvent.content_type == content_type)
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .order_by(SubtitleEvent.line_index)
        ).all())

        events_snapshot = [
            {
                "id": e.id,
                "line_index": e.line_index,
                "name": e.name,
                "source_text": e.source_text,
                "translated_text": e.translated_text,
                "translation_confidence": e.translation_confidence,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
                "untouchable": bool(e.is_user_edited or e.is_locked or e.is_approved),
            }
            for e in target_events
        ]

    if not events_snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events in target range for chunk {chunk_index}")

    progress(0.3, f"Checking {len(events_snapshot)} events")

    cps_limit = ctx.options.cps_limit
    max_row_chars = ctx.options.max_row_chars
    confidence_threshold = ctx.options.translation_confidence_flag_threshold

    # Deterministic rewrap before the readability check: long_row then only
    # flags what a balanced two-row split can't fix.
    rebalanced: dict[int, str] = {}
    if ctx.options.auto_line_break:
        for snap in events_snapshot:
            if snap["untouchable"]:
                continue
            fixed = rebalance_rows(snap["translated_text"] or "", max_row_chars)
            if fixed is not None:
                snap["translated_text"] = fixed
                rebalanced[snap["id"]] = fixed

    collected: list[dict] = []
    strong_findings = 0
    for snap in events_snapshot:
        translated = snap["translated_text"] or ""
        if not translated.strip():
            continue

        gender = identities.get(snap["name"] or "", (None, None))[1]

        findings = []
        findings += check_gender_agreement(translated, gender)
        findings += check_tv_mixed_in_line(translated)
        if snap["name"] and snap["name"] in speaker_modes:
            findings += check_tv_against_pairs(translated, speaker_modes[snap["name"]])
        if vocatives:
            findings += check_vocative(translated, vocatives)
        findings += check_readability(translated, snap["end_ms"] - snap["start_ms"],
                                      cps_limit, max_row_chars)
        findings += check_untranslated_english(
            snap["source_text"] or "", translated, english_exclude)

        confidence = snap["translation_confidence"]
        if confidence is not None and confidence < confidence_threshold:
            findings.append((
                "low_confidence",
                f"Model reported low confidence ({confidence:.2f}) for this line.",
                {"confidence": confidence, "threshold": confidence_threshold},
            ))

        for qa_type, message, details in findings:
            if qa_type in _STRONG_QA_TYPES:
                strong_findings += 1
            collected.append(dict(
                file_id=file_id,
                subtitle_event_id=snap["id"],
                severity="warning",
                qa_type=qa_type,
                message=message,
                details_json=json.dumps(details) if details else None,
                is_resolved=0,
                created_at=now,
            ))

    needs_polish = strong_findings > 0 and polish_attempts < _MAX_POLISH_ATTEMPTS
    new_status = "needs_polish" if needs_polish else "final_reviewed"

    progress(0.7, f"Writing {len(collected)} finding(s), chunk → {new_status}")

    target_event_ids = [s["id"] for s in events_snapshot]
    with SyncSessionLocal() as session:
        # Persist auto-rebalanced rows (still AI pipeline output, so the
        # revert-to-AI reference follows it, mirroring polish_chunk).
        for event_id, fixed_text in rebalanced.items():
            event = session.get(SubtitleEvent, event_id)
            if event is None or event.is_user_edited or event.is_locked:
                continue
            event.translated_text = fixed_text
            event.original_ai_translated_text = fixed_text
            event.updated_at = now

        # Replace stale findings from a previous run of this review.
        if target_event_ids:
            session.execute(
                delete(QaItem).where(
                    QaItem.subtitle_event_id.in_(target_event_ids),
                    QaItem.qa_type.in_(sorted(FINAL_REVIEW_QA_TYPES)),
                    QaItem.is_resolved == 0,
                )
            )
        if collected:
            session.execute(QaItem.__table__.insert(), collected)

        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = new_status
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "warnings_created": len(collected),
            "needs_polish": needs_polish,
            "rows_rebalanced": len(rebalanced),
        },
        error_code=None,
        error_message=None,
    )

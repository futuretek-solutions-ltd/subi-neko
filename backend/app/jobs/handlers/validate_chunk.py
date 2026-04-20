from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.database import SyncSessionLocal
from app.db.models import File, QaItem, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

# Patterns for text corruption detection
_CORRUPTION_PREFIXES = re.compile(
    r"^\s*(translation\s*:|note\s*:|translator\s*:|output\s*:|result\s*:)",
    re.IGNORECASE,
)
_MARKDOWN_FENCE = re.compile(r"```")
_JSON_LIKE = re.compile(r"^\s*[\[{]")
_NUMBERING = re.compile(r"^\s*(\d+[\.\)]\s+|[-*•]\s+)")
_BROKEN_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LEADING_ASS_OVERRIDE_BLOCKS = re.compile(r"^\s*(?:\{\\[^}]*\}\s*)+")


# ---------------------------------------------------------------------------
# Individual checks — each returns a list of (qa_type, message, details)
# An empty list means the event passed.
# ---------------------------------------------------------------------------

def _check_missing_translation(event: SubtitleEvent) -> list[tuple[str, str, dict]]:
    if event.translated_text is None or not event.translated_text.strip():
        return [("missing_translation", "Translated text is empty.", {})]
    return []


def _count_ass_tag_blocks(text: str) -> tuple[int, int]:
    """Return (open_brace_count, close_brace_count)."""
    return text.count("{"), text.count("}")


def _has_unclosed_block(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


def _check_formatting_tag_mismatch(event: SubtitleEvent) -> list[tuple[str, str, dict]]:
    src = event.source_text or ""
    tgt = event.translated_text or ""

    src_open, src_close = _count_ass_tag_blocks(src)
    tgt_open, tgt_close = _count_ass_tag_blocks(tgt)

    details: dict[str, Any] = {}
    failed = False

    if src_open != tgt_open or src_close != tgt_close:
        details["source_open"] = src_open
        details["source_close"] = src_close
        details["translated_open"] = tgt_open
        details["translated_close"] = tgt_close
        failed = True

    if _has_unclosed_block(tgt):
        details["unclosed_block"] = True
        failed = True

    if failed:
        return [("formatting_tag_mismatch",
                 "ASS formatting tags are missing or malformed.",
                 details)]
    return []


_ASS_ESCAPES = [r"\N", r"\n", r"\h"]


def _check_escape_mismatch(event: SubtitleEvent) -> list[tuple[str, str, dict]]:
    src = event.source_text or ""
    tgt = event.translated_text or ""

    details: dict[str, Any] = {}
    failed = False

    for esc in _ASS_ESCAPES:
        src_count = src.count(esc)
        tgt_count = tgt.count(esc)
        if src_count != tgt_count:
            details[esc] = {"source": src_count, "translated": tgt_count}
            failed = True

    if failed:
        return [("escape_mismatch",
                 "ASS escape sequences were not preserved.",
                 details)]
    return []


def _check_locked_line_modified(event: SubtitleEvent) -> list[tuple[str, str, dict]]:
    if not event.is_locked:
        return []
    if event.translated_text != event.source_text:
        return [("locked_line_modified",
                 "Locked event was modified.",
                 {"source_text": event.source_text,
                  "translated_text": event.translated_text})]
    return []


def _check_text_corruption(event: SubtitleEvent) -> list[tuple[str, str, dict]]:
    text = event.translated_text or ""
    text_for_prefix_checks = _LEADING_ASS_OVERRIDE_BLOCKS.sub("", text)
    reasons = []

    if _CORRUPTION_PREFIXES.match(text_for_prefix_checks):
        reasons.append("assistant_prefix")
    if _MARKDOWN_FENCE.search(text):
        reasons.append("markdown_fence")
    if _JSON_LIKE.match(text_for_prefix_checks):
        reasons.append("json_like_output")
    if _NUMBERING.match(text_for_prefix_checks):
        reasons.append("numbering_or_bullet")
    if _BROKEN_CONTROL.search(text):
        reasons.append("broken_control_characters")

    if reasons:
        return [("text_corruption",
                 "Translated text appears corrupted or contains non-subtitle output.",
                 {"reasons": reasons})]
    return []


_CHECKS = [
    _check_missing_translation,
    _check_formatting_tag_mismatch,
    _check_escape_mismatch,
    _check_locked_line_modified,
    _check_text_corruption,
]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register_job_handler("validate_chunk")
def validate_chunk(
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

        translate_from = chunk.translate_from_line
        translate_to = chunk.translate_to_line

        target_events: list[SubtitleEvent] = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

        # Snapshot data before closing session
        events_snapshot = [
            {
                "id": e.id,
                "line_index": e.line_index,
                "source_text": e.source_text,
                "translated_text": e.translated_text,
                "is_locked": e.is_locked,
            }
            for e in target_events
        ]

    if not events_snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events in target range for chunk {chunk_index}")

    progress(0.2, f"Validating {len(events_snapshot)} events")

    # Run checks in-memory — no DB access needed
    collected_errors: list[dict] = []
    failed_event_ids: set[int] = set()

    for snap in events_snapshot:
        event_errors: list[tuple[str, str, dict]] = []

        # Build a lightweight proxy object for check functions
        class _Proxy:
            translated_text = snap["translated_text"]
            source_text = snap["source_text"]
            is_locked = snap["is_locked"]

        proxy = _Proxy()

        for check_fn in _CHECKS:
            event_errors.extend(check_fn(proxy))  # type: ignore[arg-type]

        if event_errors:
            failed_event_ids.add(snap["id"])
            for qa_type, message, details in event_errors:
                collected_errors.append(dict(
                    file_id=file_id,
                    subtitle_event_id=snap["id"],
                    severity="error",
                    qa_type=qa_type,
                    message=message,
                    details_json=json.dumps(details) if details else None,
                    is_resolved=0,
                    created_at=now,
                ))

    target_event_ids = [s["id"] for s in events_snapshot]
    has_errors = len(collected_errors) > 0
    error_types = sorted({e["qa_type"] for e in collected_errors})

    progress(0.6, f"Writing results ({len(collected_errors)} errors)")

    with SyncSessionLocal() as session:
        # Delete all unresolved qa_items for target events (validation resets the full review state)
        if target_event_ids:
            session.execute(
                delete(QaItem).where(
                    QaItem.subtitle_event_id.in_(target_event_ids),
                    QaItem.is_resolved == 0,
                )
            )

        # Update translation_status on each target event
        for snap in events_snapshot:
            event = session.get(SubtitleEvent, snap["id"])
            if event is None:
                continue
            event.translation_status = "rejected" if snap["id"] in failed_event_ids else "validated"
            event.updated_at = now

        # Insert new qa_items
        if collected_errors:
            session.execute(QaItem.__table__.insert(), collected_errors)

        # Update chunk status
        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            if has_errors:
                # First repair attempt: allow repair; further failures stop here.
                if chunk.repair_attempt_count == 0:
                    chunk.status = "validate_trans_failed"
                else:
                    chunk.status = "validate_repair_failed"
            else:
                chunk.status = "validated"
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "valid": not has_errors,
            "validated_events": len(events_snapshot),
            "error_count": len(collected_errors),
            "error_types": error_types,
        },
        error_code=None,
        error_message=None,
    )

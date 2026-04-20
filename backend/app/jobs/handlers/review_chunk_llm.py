from __future__ import annotations

import json
import logging

from app.jobs.handlers.utils import sanitize_llm_json
from collections import defaultdict
from datetime import datetime
from typing import Any

from openai import OpenAI
from sqlalchemy import select

from app.core.database import SyncSessionLocal
from app.db.models import QaItem, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

_CONTEXT_SIZE = 2  # lines before and after each flagged line


# ---------------------------------------------------------------------------
# Window building
# ---------------------------------------------------------------------------

def _build_windows(
    all_events: list[dict],
    flagged_ids: set[int],
) -> list[list[dict]]:
    """
    Expand each flagged event by ±CONTEXT_SIZE positions in the sorted list,
    merge overlapping/adjacent ranges, and return windows where each entry
    carries a 'role' of 'target' or 'context'.
    """
    n = len(all_events)
    flagged_positions: set[int] = {
        i for i, e in enumerate(all_events) if e["id"] in flagged_ids
    }

    if not flagged_positions:
        return []

    # Build (start, end, target_positions_in_range) per flagged event
    ranges: list[tuple[int, int, set[int]]] = []
    for pos in sorted(flagged_positions):
        start = max(0, pos - _CONTEXT_SIZE)
        end = min(n - 1, pos + _CONTEXT_SIZE)
        ranges.append((start, end, {pos}))

    # Merge overlapping or adjacent ranges
    merged: list[list[Any]] = []
    for start, end, targets in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].update(targets)
        else:
            merged.append([start, end, targets])

    # Build window dicts
    windows: list[list[dict]] = []
    for start, end, target_positions in merged:
        window: list[dict] = []
        for i in range(start, end + 1):
            entry = dict(all_events[i])
            entry["role"] = "target" if i in target_positions else "context"
            window.append(entry)
        windows.append(window)

    return windows


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _format_window(window: list[dict]) -> str:
    lines: list[str] = []
    for entry in window:
        role = "[TARGET] " if entry["role"] == "target" else "[CONTEXT]"
        speaker = f"[{entry['speaker']}]" if entry.get("speaker") else ""
        src = entry["source_text"] or ""
        tgt = entry["translated_text"] or ""
        lines.append(f"{role} {entry['line_index']}{' ' + speaker if speaker else ''}: {src} → {tgt}")
    return "\n".join(lines)


def _build_user_message(windows: list[list[dict]]) -> str:
    sections: list[str] = []
    for idx, window in enumerate(windows, 1):
        sections.append(f"=== Window {idx} ===\n{_format_window(window)}")
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register_job_handler("review_chunk_llm")
def review_chunk_llm(
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

        events: list[SubtitleEvent] = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

        all_event_ids = [e.id for e in events]

        # Find which events have unresolved qa_items
        qa_counts: dict[int, int] = defaultdict(int)
        if all_event_ids:
            qa_rows = session.execute(
                select(QaItem.subtitle_event_id)
                .where(QaItem.subtitle_event_id.in_(all_event_ids))
                .where(QaItem.is_resolved == 0)
            ).all()
            for row in qa_rows:
                qa_counts[row[0]] += 1

        snapshot = [
            {
                "id": e.id,
                "line_index": e.line_index,
                "source_text": e.source_text,
                "translated_text": e.translated_text,
                "speaker": e.name or "",
            }
            for e in events
        ]

    if not snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events in target range for chunk {chunk_index}")

    flagged_ids = {event_id for event_id, count in qa_counts.items() if count > 0}

    flagged_only = ctx.options.llm_review_flagged_only

    if flagged_only and not flagged_ids:
        # No flagged events and we're in flagged-only mode — nothing to review
        with SyncSessionLocal() as session:
            chunk = session.scalar(
                select(SubtitleChunk)
                .where(SubtitleChunk.file_id == file_id)
                .where(SubtitleChunk.chunk_index == chunk_index)
            )
            if chunk is not None:
                chunk.status = "llm_reviewed"
                chunk.updated_at = now
            session.commit()
        return JobResult(
            status="succeeded",
            result={"windows_reviewed": 0, "issues_found": 0, "suggestions_created": 0},
            error_code=None,
            error_message=None,
        )

    if flagged_only:
        windows = _build_windows(snapshot, flagged_ids)
        progress(0.2, f"Reviewing {len(windows)} window(s) covering {len(flagged_ids)} flagged lines")
    else:
        # Send every event in the chunk to the LLM
        windows = [
            [dict(entry, role="target") for entry in snapshot]
        ]
        progress(0.2, f"Reviewing full chunk ({len(snapshot)} events)")

    model = ctx.options.openai_model_better
    if not model:
        return JobResult(status="failed", result=None,
                         error_code="MODEL_NOT_CONFIGURED",
                         error_message="OPENAI_MODEL_BETTER is not configured")

    system_prompt = ctx.options.resolved_review_prompt().strip()
    user_message = _build_user_message(windows)

    client = OpenAI(
        api_key=ctx.options.openai_api_key or "no-key",
        base_url=ctx.options.openai_api_base or None,
    )

    progress(0.35, "Sending to model")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(sanitize_llm_json(raw))
    except json.JSONDecodeError as exc:
        return JobResult(status="failed", result=None,
                         error_code="LLM_PARSE_ERROR",
                         error_message=f"Model returned invalid JSON: {exc}")

    issues: list[dict] = parsed.get("issues", [])
    progress(0.75, f"Model found {len(issues)} issue(s), writing QA items")

    # Build line_index → event_id map
    line_to_id = {e["line_index"]: e["id"] for e in snapshot}

    collected_warnings: list[dict] = []
    for issue in issues:
        line_index = issue.get("i")
        event_id = line_to_id.get(line_index)
        if event_id is None:
            logger.warning("LLM returned unknown line_index %s, skipping", line_index)
            continue

        details = {
            "type": issue.get("type"),
            "description": issue.get("description"),
            "suggestion": issue.get("suggestion"),
        }
        collected_warnings.append(dict(
            file_id=file_id,
            subtitle_event_id=event_id,
            severity="warning",
            qa_type="llm_review",
            message=issue.get("description") or "LLM review suggestion",
            details_json=json.dumps(details),
            is_resolved=0,
            created_at=now,
        ))

    with SyncSessionLocal() as session:
        if collected_warnings:
            session.execute(QaItem.__table__.insert(), collected_warnings)

        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = "llm_reviewed"
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "windows_reviewed": len(windows),
            "issues_found": len(issues),
            "suggestions_created": len(collected_warnings),
        },
        error_code=None,
        error_message=None,
    )

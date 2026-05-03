from __future__ import annotations

import json
import logging

from app.jobs.handlers.utils import sanitize_llm_json
from datetime import datetime
from typing import Any

from openai import OpenAI
from sqlalchemy import select

from app.core.database import SyncSessionLocal
from app.db.models import File, ProjectCharacter, ProjectSpeaker, QaItem, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.handlers.prompt_context import (
    build_character_block,
    build_unmapped_speaker_block,
    load_prompt_characters,
    load_unmapped_gendered_speakers,
)
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

_CONTEXT_WINDOW = 2  # lines before and after each failed line

_REPAIR_RULES = """
Structural rules (never break):
- Preserve ALL ASS inline tags exactly: {\\an8}, {\\i1}, {\\pos(x,y)}, etc.
- { and } counts must match the source line exactly
- Preserve \\N, \\n, \\h escapes exactly as in source
- No prefixes, numbering, bullets, markdown, or meta-commentary
- Output subtitle text only

Return a single JSON object:
{"repairs": [{"i": <line_index>, "t": "<fixed translation>"}]}
Include exactly one entry per FAILED line. Do NOT include CONTEXT lines.
"""


def _build_repair_block(
    rejected: list[dict],
    all_events_by_pos: list[dict],
    qa_errors: dict[int, list[str]],
) -> str:
    """
    Build the user message block for repair.

    rejected: list of event dicts (line_index, source_text, translated_text, id)
    all_events_by_pos: all dialogue events in chunk, sorted by line_index, as dicts
    qa_errors: event_id → list of qa_type strings
    """
    pos_map = {e["line_index"]: i for i, e in enumerate(all_events_by_pos)}
    total = len(all_events_by_pos)

    parts = []
    for ev in rejected:
        li = ev["line_index"]
        pos = pos_map.get(li)
        errors = qa_errors.get(ev["id"], [])

        lines = []
        lines.append(f"### FAILED line {li} — errors: {', '.join(errors) if errors else 'unknown'}")
        lines.append(f"  source: {ev['source_text']}")
        if ev["translated_text"]:
            lines.append(f"  faulty: {ev['translated_text']}")

        # context before
        ctx_before = []
        if pos is not None:
            for i in range(max(0, pos - _CONTEXT_WINDOW), pos):
                ctx_ev = all_events_by_pos[i]
                text = ctx_ev["translated_text"] or ctx_ev["source_text"]
                ctx_before.append(f"  [CONTEXT {ctx_ev['line_index']}]: {text}")
        if ctx_before:
            lines.append("Context before:")
            lines.extend(ctx_before)

        # context after
        ctx_after = []
        if pos is not None:
            for i in range(pos + 1, min(total, pos + 1 + _CONTEXT_WINDOW)):
                ctx_ev = all_events_by_pos[i]
                text = ctx_ev["translated_text"] or ctx_ev["source_text"]
                ctx_after.append(f"  [CONTEXT {ctx_ev['line_index']}]: {text}")
        if ctx_after:
            lines.append("Context after:")
            lines.extend(ctx_after)

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


@register_job_handler("repair_chunk")
def repair_chunk(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    chunk_index: int = payload["chunk_index"]
    model: str = payload.get("model") or ctx.options.openai_model_better or ctx.options.openai_model_cheap or "gpt-4o"
    now = datetime.utcnow().isoformat()

    if not ctx.options.openai_api_key and not ctx.options.openai_api_base:
        return JobResult(status="failed", result=None,
                         error_code="OPENAI_API_KEY_MISSING",
                         error_message="OPENAI_API_KEY option is not configured")

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
        file = session.get(File, file_id)
        characters: list[ProjectCharacter] = []
        unmapped_speakers: list[ProjectSpeaker] = []
        if file is not None:
            characters = load_prompt_characters(session, file.project_id)
            unmapped_speakers = load_unmapped_gendered_speakers(session, file.project_id)

        # All dialogue events in chunk range, ordered
        all_events = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

        all_events_data = [
            {
                "id": e.id,
                "line_index": e.line_index,
                "source_text": e.source_text,
                "translated_text": e.translated_text,
                "translation_status": e.translation_status,
            }
            for e in all_events
        ]

        rejected_data = [e for e in all_events_data if e["translation_status"] == "rejected"]

        if not rejected_data:
            return JobResult(status="succeeded", result={"repaired_events": 0},
                             error_code=None, error_message=None)

        rejected_ids = [e["id"] for e in rejected_data]

        # Load QA errors for rejected events
        qa_rows = list(session.scalars(
            select(QaItem)
            .where(QaItem.subtitle_event_id.in_(rejected_ids))
            .where(QaItem.is_resolved == 0)
        ).all())
        qa_errors: dict[int, list[str]] = {}
        for qa in qa_rows:
            qa_errors.setdefault(qa.subtitle_event_id, []).append(qa.qa_type)

        char_snapshot = list(characters)
        speaker_snapshot = list(unmapped_speakers)

    progress(0.2, f"Building repair prompt for {len(rejected_data)} rejected event(s)")

    system_prompt = ctx.options.resolved_repair_prompt().strip()
    system_prompt += f"\n{_REPAIR_RULES}"

    repair_block = _build_repair_block(rejected_data, all_events_data, qa_errors)
    user_parts = []
    char_block = build_character_block(char_snapshot)
    speaker_block = build_unmapped_speaker_block(speaker_snapshot)
    if char_block:
        user_parts.append(f"## Characters\n{char_block}")
    if speaker_block:
        user_parts.append(f"## Unmapped Speakers\n{speaker_block}")
    user_parts.append(f"## Lines to Repair\n\n{repair_block}")
    user_message = "\n\n".join(user_parts)

    progress(0.4, f"Calling OpenAI ({model})")

    client = OpenAI(
        api_key=ctx.options.openai_api_key or "no-key",
        base_url=ctx.options.openai_api_base or None,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        return JobResult(status="failed", result=None,
                         error_code="OPENAI_API_ERROR",
                         error_message=str(exc))

    raw_content = response.choices[0].message.content or ""

    progress(0.7, "Parsing response")

    try:
        parsed = json.loads(sanitize_llm_json(raw_content))
        repairs: list[dict] = parsed["repairs"]
    except Exception as exc:
        return JobResult(status="failed", result=None,
                         error_code="RESPONSE_PARSE_ERROR",
                         error_message=f"Could not parse model response: {exc}\n\nRaw: {raw_content[:500]}")

    repair_map: dict[int, str] = {}
    for entry in repairs:
        try:
            repair_map[int(entry["i"])] = str(entry["t"])
        except (KeyError, ValueError, TypeError):
            continue

    progress(0.85, "Writing repaired translations")

    repaired_count = 0
    rejected_by_line: dict[int, int] = {e["line_index"]: e["id"] for e in rejected_data}

    with SyncSessionLocal() as session:
        for line_index, event_id in rejected_by_line.items():
            text = repair_map.get(line_index)
            if text is None:
                logger.warning("No repair returned for line_index=%d (chunk %d, file %d)",
                               line_index, chunk_index, file_id)
                continue
            event = session.get(SubtitleEvent, event_id)
            if event is None:
                continue
            event.translated_text = text
            if event.original_ai_translated_text is None:
                event.original_ai_translated_text = text
            event.translation_status = "translated"
            event.updated_at = now
            repaired_count += 1

        # Reset chunk status so validator can run again.
        # Increment repair_attempt_count so validate_chunk knows a repair was attempted.
        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = "translated"
            chunk.repair_attempt_count = (chunk.repair_attempt_count or 0) + 1
            chunk.last_error_code = None
            chunk.last_error_message = None
            chunk.failed_job_type = None
            chunk.model = model
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"repaired_events": repaired_count},
        error_code=None,
        error_message=None,
    )

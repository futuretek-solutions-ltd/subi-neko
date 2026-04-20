from __future__ import annotations

import json
import logging

from app.jobs.handlers.utils import sanitize_llm_json
from datetime import datetime
from typing import Any

from openai import OpenAI
from sqlalchemy import select

from app.core.database import SyncSessionLocal
from app.db.models import File, ProjectCharacter, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

def _build_character_block(characters: list[ProjectCharacter]) -> str:
    lines = []
    for c in characters:
        extras = [(k, v) for k, v in [
            ("gender", c.gender),
            ("social_position", c.social_position),
            ("note", c.note),
        ] if v and v.strip()]
        if not extras:
            continue  # skip characters with name only
        parts = [c.name] + [f"{k}: {v}" for k, v in extras]
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def _build_dialogue_block(
    context_events: list[SubtitleEvent],
    target_events: list[SubtitleEvent],
) -> str:
    lines = []
    for e in context_events:
        lines.append(f"[CONTEXT] {e.line_index}: {e.source_text}")
    for e in target_events:
        lines.append(f"[TARGET] {e.line_index}: {e.source_text}")
    return "\n".join(lines)


@register_job_handler("translate_chunk")
def translate_chunk(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    chunk_index: int = payload["chunk_index"]
    model: str = payload.get("model") or ctx.options.openai_model_cheap or "gpt-4o-mini"
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
        ctx_from = chunk.context_prepend_from_line
        ctx_to = chunk.context_prepend_to_line

        # Load characters via project
        file = session.get(File, file_id)
        characters: list[ProjectCharacter] = []
        if file is not None:
            characters = list(session.scalars(
                select(ProjectCharacter).where(ProjectCharacter.project_id == file.project_id)
            ).all())

        # Load subtitle events for target range
        target_events = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.event_type == "dialogue")
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .order_by(SubtitleEvent.line_index)
        ).all())

        # Load subtitle events for context range (may be None if no context window)
        context_events: list[SubtitleEvent] = []
        if ctx_from is not None and ctx_to is not None:
            context_events = list(session.scalars(
                select(SubtitleEvent)
                .where(SubtitleEvent.file_id == file_id)
                .where(SubtitleEvent.event_type == "dialogue")
                .where(SubtitleEvent.line_index >= ctx_from)
                .where(SubtitleEvent.line_index <= ctx_to)
                .order_by(SubtitleEvent.line_index)
            ).all())

        char_snapshot = list(characters)
        ctx_snapshot = list(context_events)
        tgt_snapshot = list(target_events)
        target_ids = {e.line_index: e.id for e in target_events}

    if not tgt_snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events found in target range for chunk {chunk_index}")

    progress(0.2, f"Building prompt ({len(tgt_snapshot)} target, {len(ctx_snapshot)} context lines)")

    system_prompt = ctx.options.resolved_translation_prompt().strip()

    char_block= _build_character_block(char_snapshot)
    dialogue_block = _build_dialogue_block(ctx_snapshot, tgt_snapshot)

    user_parts = []
    if char_block:
        user_parts.append(f"## Characters\n{char_block}")
    user_parts.append(f"## Dialogue\n{dialogue_block}")
    user_message = "\n\n".join(user_parts)

    progress(0.35, f"Calling OpenAI ({model})")

    client = OpenAI(
        api_key=ctx.options.openai_api_key or "no-key",
        base_url=ctx.options.openai_api_base,
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
        translations: list[dict] = parsed["translations"]
    except Exception as exc:
        return JobResult(status="failed", result=None,
                         error_code="RESPONSE_PARSE_ERROR",
                         error_message=f"Could not parse model response: {exc}\n\nRaw: {raw_content[:500]}")

    # Build line_index → translated_text map
    translation_map: dict[int, str] = {}
    for entry in translations:
        try:
            translation_map[int(entry["i"])] = str(entry["t"])
        except (KeyError, ValueError, TypeError):
            continue

    progress(0.85, "Writing translations")

    with SyncSessionLocal() as session:
        # Update each target event
        for line_index, event_id in target_ids.items():
            text = translation_map.get(line_index)
            if text is None:
                logger.warning("No translation returned for line_index=%d (chunk %d, file %d)",
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

        # Mark chunk as translated
        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = "translated"
            chunk.model = model
            chunk.updated_at = now

        session.commit()

    translated_count = len(translation_map)
    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "translated_events": translated_count,
            "context_events": len(ctx_snapshot),
            "model_used": model,
        },
        error_code=None,
        error_message=None,
    )

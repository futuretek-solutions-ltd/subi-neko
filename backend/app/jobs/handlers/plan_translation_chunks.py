from __future__ import annotations

import logging
from math import ceil
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.database import SyncSessionLocal
from app.db.models import File, ProjectSpeaker, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler
from app.subs.content_classification import classify_content_type

logger = logging.getLogger(__name__)

SPEAKER_TAG_REASON = "speaker_tag"


def _reset_machine_translation(event: SubtitleEvent) -> None:
    """A content-type change invalidates a machine translation (wrong prompt
    path, possibly wrong register). User edits are never touched."""
    if event.translated_text is not None and not event.is_user_edited:
        event.translated_text = None
        event.original_ai_translated_text = None
        event.translation_confidence = None
        event.translation_status = "pending"


def _apply_speaker_content_tags(session, file: File, now: str) -> int:
    """Re-type events according to speaker content tags (and revert events
    whose speaker tag was removed). Runs before partitioning so tagged
    speakers' lines land in the matching content-type chunks. Idempotent."""
    tag_by_name: dict[str, str] = {
        name: tag
        for name, tag in session.execute(
            select(ProjectSpeaker.name, ProjectSpeaker.content_tag)
            .where(ProjectSpeaker.project_id == file.project_id)
            .where(ProjectSpeaker.content_tag.is_not(None))
        ).all()
    }

    events = session.scalars(
        select(SubtitleEvent)
        .where(SubtitleEvent.file_id == file.id)
        .where(SubtitleEvent.event_type == "dialogue")
    ).all()

    changed = 0
    for event in events:
        tag = tag_by_name.get(event.name) if event.name else None
        if tag is not None:
            if event.content_type != tag or event.content_type_reason != SPEAKER_TAG_REASON:
                if event.content_type != tag:
                    _reset_machine_translation(event)
                event.content_type = tag
                event.content_type_reason = SPEAKER_TAG_REASON
                event.updated_at = now
                changed += 1
        elif event.content_type_reason == SPEAKER_TAG_REASON:
            # Tag removed — restore the heuristic classification.
            content_type, reason = classify_content_type(
                event.event_type, event.style or "", event.source_text or "")
            if event.content_type != content_type:
                _reset_machine_translation(event)
            event.content_type = content_type
            event.content_type_reason = reason
            event.updated_at = now
            changed += 1

    if changed:
        session.commit()
    return changed


def _effective_chunk_size(total_lines: int, configured_chunk_size: int) -> int:
    if configured_chunk_size <= 0:
        return configured_chunk_size

    chunk_count = ceil(total_lines / configured_chunk_size)
    remainder = total_lines % configured_chunk_size
    if chunk_count <= 1 or remainder == 0:
        return configured_chunk_size

    if remainder * 10 >= configured_chunk_size:
        return configured_chunk_size

    return ceil(total_lines / (chunk_count - 1))


# Partition order is deterministic so chunk_index stays stable across
# regenerations of the same file's chunk plan.
_CONTENT_TYPE_PARTITIONS = ["dialogue", "sign", "karaoke", "song"]


def _build_chunks_for_partition(
    file_id: int,
    content_type: str,
    lines: list[int],
    configured_chunk_size: int,
    start_chunk_index: int,
    now: str,
) -> list[dict]:
    chunk_rows: list[dict] = []
    total = len(lines)
    chunk_size = _effective_chunk_size(total, configured_chunk_size)

    for offset, start_pos in enumerate(range(0, total, chunk_size)):
        chunk_lines = lines[start_pos: start_pos + chunk_size]

        translate_from_line = chunk_lines[0]
        translate_to_line = chunk_lines[-1]

        # Context is computed at runtime by translate_chunk (chronological,
        # cross-partition, with prior translations) — the context_prepend_*
        # columns are deprecated and no longer populated.
        chunk_rows.append(dict(
            file_id=file_id,
            chunk_index=start_chunk_index + offset,
            translate_from_line=translate_from_line,
            translate_to_line=translate_to_line,
            context_prepend_from_line=None,
            context_prepend_to_line=None,
            content_type=content_type,
            status="pending",
            model=None,
            created_at=now,
            updated_at=now,
        ))

    return chunk_rows


@register_job_handler("plan_translation_chunks")
def plan_translation_chunks(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    now = datetime.utcnow().isoformat()

    chunk_size = ctx.options.chunk_size

    progress(0.05, "Loading dialogue events")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id)
        if file is None:
            return JobResult(status="failed", result=None,
                             error_code="FILE_NOT_FOUND",
                             error_message=f"File id={file_id} not found")

        retagged = _apply_speaker_content_tags(session, file, now)
        if retagged:
            progress(0.15, f"Re-typed {retagged} events from speaker content tags")

        # All Dialogue-type events in line order, with their content_type classification
        rows = session.execute(
            select(SubtitleEvent.line_index, SubtitleEvent.content_type)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all()

    if not rows:
        return JobResult(status="succeeded", result={"chunks_created": 0},
                         error_code=None, error_message=None)

    progress(0.3, f"Building chunks from {len(rows)} dialogue-type events")

    lines_by_content_type: dict[str, list[int]] = {ct: [] for ct in _CONTENT_TYPE_PARTITIONS}
    for line_index, content_type in rows:
        lines_by_content_type.setdefault(content_type, []).append(line_index)

    chunk_rows: list[dict] = []
    next_chunk_index = 0
    for content_type in _CONTENT_TYPE_PARTITIONS:
        lines = lines_by_content_type.get(content_type) or []
        if not lines:
            continue
        partition_chunks = _build_chunks_for_partition(
            file_id, content_type, lines, chunk_size,
            next_chunk_index, now,
        )
        chunk_rows.extend(partition_chunks)
        next_chunk_index += len(partition_chunks)

    progress(0.7, f"Writing {len(chunk_rows)} chunks")

    with SyncSessionLocal() as session:
        session.execute(
            delete(SubtitleChunk).where(SubtitleChunk.file_id == file_id)
        )
        session.execute(
            SubtitleChunk.__table__.insert(),
            chunk_rows,
        )
        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"chunks_created": len(chunk_rows)},
        error_code=None,
        error_message=None,
    )

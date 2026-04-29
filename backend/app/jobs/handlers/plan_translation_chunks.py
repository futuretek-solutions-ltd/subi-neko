from __future__ import annotations

import logging
from math import ceil
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.core.database import SyncSessionLocal
from app.db.models import File, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)


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


@register_job_handler("plan_translation_chunks")
def plan_translation_chunks(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    now = datetime.utcnow().isoformat()

    chunk_size = ctx.options.chunk_size
    prepend_context_size = ctx.options.prepend_context_size

    progress(0.05, "Loading dialogue events")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id)
        if file is None:
            return JobResult(status="failed", result=None,
                             error_code="FILE_NOT_FOUND",
                             error_message=f"File id={file_id} not found")

        # All Dialogue events in line order — only their line_index values needed
        dialogue_lines: list[int] = list(session.scalars(
            select(SubtitleEvent.line_index)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

    if not dialogue_lines:
        return JobResult(status="succeeded", result={"chunks_created": 0},
                         error_code=None, error_message=None)

    progress(0.3, f"Building chunks from {len(dialogue_lines)} dialogue events")

    # Group into contiguous chunks of chunk_size
    chunk_rows: list[dict] = []
    total = len(dialogue_lines)
    chunk_size = _effective_chunk_size(total, chunk_size)

    for chunk_index, start_pos in enumerate(range(0, total, chunk_size)):
        chunk_lines = dialogue_lines[start_pos: start_pos + chunk_size]

        translate_from_line = chunk_lines[0]
        translate_to_line = chunk_lines[-1]

        # Context: up to prepend_context_size Dialogue lines immediately before this chunk
        context_lines = dialogue_lines[max(0, start_pos - prepend_context_size): start_pos]
        if context_lines:
            context_prepend_from_line = context_lines[0]
            context_prepend_to_line = context_lines[-1]
        else:
            context_prepend_from_line = None
            context_prepend_to_line = None

        chunk_rows.append(dict(
            file_id=file_id,
            chunk_index=chunk_index,
            translate_from_line=translate_from_line,
            translate_to_line=translate_to_line,
            context_prepend_from_line=context_prepend_from_line,
            context_prepend_to_line=context_prepend_to_line,
            status="pending",
            model=None,
            created_at=now,
            updated_at=now,
        ))

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

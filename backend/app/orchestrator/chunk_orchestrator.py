"""Chunk-level orchestrator — drives the sequential translation pipeline."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.db import options as options_store
from app.db.models import SubtitleChunk

logger = logging.getLogger(__name__)

EnqueueFn = Callable[..., Awaitable[Any]]

# Chunk status → (job_type, needs_enqueue)
# If needs_enqueue is False, orchestrator handles the transition directly.
_CHUNK_TRANSITIONS: dict[str, tuple[str, bool]] = {
    "pending":                ("translate_chunk",            True),
    "translated":             ("validate_chunk",             True),
    "validate_trans_failed":  ("repair_chunk",               True),
    "validated":              ("review_chunk_rules",         True),
    "rules_reviewed":         ("review_chunk_grammar",       True),
    # grammar_reviewed and llm_reviewed handled with custom logic
}

# Terminal statuses that require user action — orchestrator must not enqueue anything.
CHUNK_TERMINAL_STATUSES = {"job_failed", "validate_repair_failed"}


async def orchestrate_chunks(
    file_id: int,
    project_id: int,
    enqueue_fn: EnqueueFn,
) -> bool | None:
    """Drive chunk pipeline for a file.

    Returns:
        True  — all chunks are complete
        False — still working (jobs are queued/running)
        None  — blocked; one or more chunks are in a terminal error state
                requiring user action (job_failed / validate_repair_failed)
    """
    async with AsyncSessionLocal() as session:
        chunks = (await session.scalars(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .order_by(SubtitleChunk.chunk_index)
        )).all()

    if not chunks:
        return False  # no chunks planned yet

    llm_review_always = (await options_store.aget("LLM_REVIEW_ALWAYS", "0") or "").strip().lower() in ("1", "true", "yes", "on")

    any_auto_completed = False
    has_pending_work = False
    has_blocked = False

    for chunk in chunks:
        if chunk.status == "complete":
            continue

        # --- Terminal statuses: require user action, stop processing ---
        if chunk.status in CHUNK_TERMINAL_STATUSES:
            has_blocked = True
            continue

        # --- grammar_reviewed: conditional LLM or auto-complete ---
        if chunk.status in {"grammar_reviewed", "languagetool_reviewed"}:
            if llm_review_always or chunk.llm_review_needed:
                await _ensure_chunk_job(
                    enqueue_fn, "review_chunk_llm",
                    file_id, project_id, chunk.chunk_index,
                )
                has_pending_work = True
            else:
                await _set_chunk_complete(file_id, chunk.chunk_index)
                any_auto_completed = True
            continue

        # --- llm_reviewed: auto-complete ---
        if chunk.status == "llm_reviewed":
            await _set_chunk_complete(file_id, chunk.chunk_index)
            any_auto_completed = True
            continue

        has_pending_work = True

        # --- Standard transitions ---
        transition = _CHUNK_TRANSITIONS.get(chunk.status)
        if transition is None:
            logger.warning(
                "Chunk file_id=%d index=%d has unknown status '%s'",
                file_id, chunk.chunk_index, chunk.status,
            )
            continue

        job_type, _ = transition
        await _ensure_chunk_job(
            enqueue_fn, job_type,
            file_id, project_id, chunk.chunk_index,
        )

    # Blocked chunks take priority when nothing else is progressing.
    # If there's still pending work alongside blocked chunks, keep the file
    # in processing state so other chunks can finish.
    if has_blocked:
        if has_pending_work or any_auto_completed:
            return False  # some chunks still running; file stays processing
        return None  # all remaining chunks are blocked → need user action
    # If we auto-completed some chunks and nothing else is pending,
    # all chunks are now complete
    if has_pending_work:
        return False
    if any_auto_completed:
        return True
    # All were already "complete" when we started
    return True


async def _ensure_chunk_job(
    enqueue_fn: EnqueueFn,
    job_type: str,
    file_id: int,
    project_id: int,
    chunk_index: int,
) -> None:
    if job_type == "review_chunk_grammar":
        dedupe_key = f"review_chunk_grammar:file:{file_id}:chunk:{chunk_index}"
    else:
        dedupe_key = f"{job_type}:{file_id}:{chunk_index}"
    await enqueue_fn(
        job_type=job_type,
        project_id=project_id,
        payload={"file_id": file_id, "chunk_index": chunk_index},
        file_id=file_id,
        dedupe_key=dedupe_key,
    )


async def _set_chunk_complete(file_id: int, chunk_index: int) -> None:
    now = datetime.utcnow().isoformat()
    async with AsyncSessionLocal() as session:
        chunk = await session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None and chunk.status != "complete":
            chunk.status = "complete"
            chunk.updated_at = now
            await session.commit()
            logger.info(
                "Chunk file_id=%d index=%d → complete (orchestrator)",
                file_id, chunk_index,
            )

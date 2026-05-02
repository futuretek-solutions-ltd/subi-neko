"""File-level orchestrator — state machine for individual file processing."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.db.models import (
    File,
    FileBlockingReason,
    FileStatus,
    JobRecord,
    JobStatus,
    Project,
    Subtitle,
    SubtitleChunk,
    SubtitleEvent,
    SubtitleStyle,
)
from app.orchestrator.chunk_orchestrator import CHUNK_TERMINAL_STATUSES, orchestrate_chunks

logger = logging.getLogger(__name__)

EnqueueFn = Callable[..., Awaitable[Any]]


async def orchestrate_file(file_id: int, enqueue_fn: EnqueueFn) -> None:
    """Reconcile state for a single file and enqueue the next valid job."""
    async with AsyncSessionLocal() as session:
        file = await session.get(
            File, file_id,
            options=[selectinload(File.project)],
        )
        if file is None:
            logger.warning("orchestrate_file: file_id=%d not found", file_id)
            return

        project = file.project
        status = file.status

    logger.debug("orchestrate_file: id=%d status=%s project_paused=%s", file_id, status, project.is_paused)

    # Terminal / no-action statuses
    if status in (FileStatus.COMPLETED.value, FileStatus.PAUSED.value, FileStatus.FAILED.value):
        return

    # Check project-level pause
    if project.is_paused:
        return

    if status == FileStatus.NEW.value:
        await _handle_new(file_id, project.id, enqueue_fn)
    elif status == FileStatus.DISCOVERING.value:
        await _handle_discovering(file_id, project, enqueue_fn)
    elif status == FileStatus.WAITING.value:
        await _handle_waiting(file_id, project, enqueue_fn)
    elif status == FileStatus.READY.value:
        await _handle_ready(file_id, project.id, enqueue_fn)
    elif status == FileStatus.PROCESSING.value:
        await _handle_processing(file_id, project.id, enqueue_fn)
    elif status == FileStatus.REVIEW_REQUIRED.value:
        await _handle_review_required(file_id, project.id, enqueue_fn)
    elif status == FileStatus.MUXING.value:
        await _handle_muxing(file_id, project.id, enqueue_fn)


# ------------------------------------------------------------------
# Status handlers
# ------------------------------------------------------------------

async def _handle_new(file_id: int, project_id: int, enqueue_fn: EnqueueFn) -> None:
    await _ensure_file_job(enqueue_fn, "inspect_mkv", file_id, project_id)


async def _handle_discovering(
    file_id: int, project: Project, enqueue_fn: EnqueueFn,
) -> None:
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None:
            return

        has_track = file.subtitle_track_index is not None

        has_subtitle = await session.scalar(
            select(func.count()).select_from(Subtitle).where(Subtitle.file_id == file_id)
        ) > 0

        # Re-read project for fresh mapping status
        fresh_project = await session.get(Project, project.id)
        mapping_status = fresh_project.speaker_mapping_status if fresh_project else project.speaker_mapping_status

    if not has_track:
        await _ensure_file_job(enqueue_fn, "inspect_mkv", file_id, project.id)
        return

    if not has_subtitle:
        await _ensure_file_job(enqueue_fn, "extract_subtitles", file_id, project.id)
        return

    # Subtitles extracted — check mapping gate
    if mapping_status not in ("mapping_complete", "no_speakers"):
        if mapping_status == "awaiting_discovery":
            # Let project orchestrator handle aggregate_speakers first
            return
        # Mapping not complete yet → file waits
        await _set_file_status(
            file_id,
            FileStatus.WAITING.value,
            FileBlockingReason.PROJECT_MAPPING_REQUIRED.value,
        )
        return

    # Mapping complete → ready
    await _set_file_status(file_id, FileStatus.READY.value, None)


async def _handle_waiting(
    file_id: int, project: Project, enqueue_fn: EnqueueFn,
) -> None:
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None:
            return
        blocking_reason = file.blocking_reason

        # Re-read project for fresh mapping status
        fresh_project = await session.get(Project, project.id)
        mapping_status = fresh_project.speaker_mapping_status if fresh_project else project.speaker_mapping_status

    if blocking_reason == FileBlockingReason.PROJECT_MAPPING_REQUIRED.value:
        if mapping_status in ("mapping_complete", "no_speakers"):
            await _set_file_status(file_id, FileStatus.READY.value, None)
        # else: keep waiting
        return

    # Partial-block: one or more chunks need user action but others may still
    # be progressing (e.g. chunk 3 is validate_repair_failed while chunk 0
    # is rules_reviewed and waiting for the grammar job).  Keep scheduling
    # work for the non-blocked chunks so the pipeline doesn't stall.
    if blocking_reason in (
        FileBlockingReason.TRANSLATION_FAILED.value,
        FileBlockingReason.VALIDATION_FAILED.value,
    ):
        all_complete = await orchestrate_chunks(file_id, project.id, enqueue_fn)
        await _handle_chunks_result(file_id, project.id, enqueue_fn, all_complete)
        return

    # All other blocking reasons: wait for user/manual action
    # (user_review_required, subtitle_missing, subtitle_parse_failed,
    #  mux_failed, paused)


async def _handle_ready(file_id: int, project_id: int, enqueue_fn: EnqueueFn) -> None:
    async with AsyncSessionLocal() as session:
        # Check fonts
        unchecked_fonts = await session.scalar(
            select(func.count())
            .select_from(SubtitleStyle)
            .where(
                SubtitleStyle.file_id == file_id,
                SubtitleStyle.font_check_status == "unchecked",
            )
        )

        # Check chunks
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
        )

    if unchecked_fonts > 0:
        await _ensure_file_job(enqueue_fn, "resolve_style_fonts", file_id, project_id)
        return

    if chunk_count == 0:
        await _ensure_file_job(enqueue_fn, "plan_translation_chunks", file_id, project_id)
        return

    # Both prerequisites met → processing
    await _set_file_status(file_id, FileStatus.PROCESSING.value, None)


async def _handle_processing(
    file_id: int, project_id: int, enqueue_fn: EnqueueFn,
) -> None:
    all_complete = await orchestrate_chunks(file_id, project_id, enqueue_fn)
    await _handle_chunks_result(file_id, project_id, enqueue_fn, all_complete)


async def _handle_chunks_result(
    file_id: int,
    project_id: int,
    enqueue_fn: EnqueueFn,
    all_complete: bool | None,
) -> None:
    if all_complete is None:
        # One or more chunks are in a terminal error state — determine blocking reason.
        await _set_file_blocked_by_chunks(file_id)
        return

    if not all_complete:
        return

    # All chunks complete. Muxing must be explicitly accepted by the user,
    # even when there are no unresolved QA items.
    await _set_file_status(
        file_id,
        FileStatus.REVIEW_REQUIRED.value,
        FileBlockingReason.USER_REVIEW_REQUIRED.value,
    )


async def _handle_review_required(
    file_id: int, project_id: int, enqueue_fn: EnqueueFn,
) -> None:
    # Stay in review until the user explicitly accepts the file.
    await _set_file_status(
        file_id,
        FileStatus.REVIEW_REQUIRED.value,
        FileBlockingReason.USER_REVIEW_REQUIRED.value,
    )


async def _handle_muxing(file_id: int, project_id: int, enqueue_fn: EnqueueFn) -> None:
    render_key = f"render_output_ass:{file_id}"
    mux_key = f"mux_output_mkv:{file_id}"

    async with AsyncSessionLocal() as session:
        render_done = await session.scalar(
            select(func.count())
            .select_from(JobRecord)
            .where(
                JobRecord.dedupe_key == render_key,
                JobRecord.status == JobStatus.COMPLETED.value,
            )
        ) > 0

        mux_done = await session.scalar(
            select(func.count())
            .select_from(JobRecord)
            .where(
                JobRecord.dedupe_key == mux_key,
                JobRecord.status == JobStatus.COMPLETED.value,
            )
        ) > 0

    if not render_done:
        await _ensure_file_job(enqueue_fn, "render_output_ass", file_id, project_id)
        return

    if not mux_done:
        await _ensure_file_job(enqueue_fn, "mux_output_mkv", file_id, project_id)
        return

    # mux handler sets file.status = completed, so if we get here
    # the job completed but status wasn't updated — fix it
    await _set_file_status(file_id, FileStatus.COMPLETED.value, None)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _ensure_file_job(
    enqueue_fn: EnqueueFn,
    job_type: str,
    file_id: int,
    project_id: int,
) -> None:
    dedupe_key = f"{job_type}:{file_id}"
    logger.debug("_ensure_file_job: type=%s file_id=%d key=%s", job_type, file_id, dedupe_key)
    await enqueue_fn(
        job_type=job_type,
        project_id=project_id,
        payload={"file_id": file_id},
        file_id=file_id,
        dedupe_key=dedupe_key,
    )


async def _set_file_status(
    file_id: int,
    status: str,
    blocking_reason: str | None,
) -> None:
    now = datetime.utcnow().isoformat()
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None:
            return
        old = file.status
        file.status = status
        file.blocking_reason = blocking_reason
        file.updated_at = now
        if status == FileStatus.COMPLETED.value:
            file.completed_at = now
        await session.commit()
    logger.info("File id=%d: %s → %s (reason=%s)", file_id, old, status, blocking_reason)


async def _set_file_blocked_by_chunks(file_id: int) -> None:
    """Set file to waiting when chunks are in a terminal error state.

    Uses the most severe blocking reason: validation_failed > translation_failed.
    """
    async with AsyncSessionLocal() as session:
        blocked_chunks = (await session.scalars(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.status.in_(list(CHUNK_TERMINAL_STATUSES)))
        )).all()

    has_validate_failed = any(c.status == "validate_repair_failed" for c in blocked_chunks)
    reason = (
        FileBlockingReason.VALIDATION_FAILED.value
        if has_validate_failed
        else FileBlockingReason.TRANSLATION_FAILED.value
    )
    await _set_file_status(file_id, FileStatus.WAITING.value, reason)

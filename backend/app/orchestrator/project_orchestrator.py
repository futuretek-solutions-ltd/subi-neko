"""Project-level orchestrator — drives the overall project lifecycle."""
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
    Project,
    ProjectStatus,
    Subtitle,
)
from app.orchestrator.file_orchestrator import orchestrate_file

logger = logging.getLogger(__name__)

EnqueueFn = Callable[..., Awaitable[Any]]

# File statuses that mean "done for project-completion purposes"
_TERMINAL_FILE_STATUSES = frozenset({
    FileStatus.COMPLETED.value,
    FileStatus.FAILED.value,
    FileStatus.PAUSED.value,
    FileStatus.REVIEW_REQUIRED.value,
})


async def orchestrate_project(project_id: int, enqueue_fn: EnqueueFn) -> None:
    """Reconcile project-level state and drive files forward."""
    async with AsyncSessionLocal() as session:
        project = await session.get(
            Project, project_id,
            options=[selectinload(Project.files)],
        )
        if project is None:
            logger.warning("orchestrate_project: project_id=%d not found", project_id)
            return

        status = project.status
        files = list(project.files)

    logger.debug(
        "orchestrate_project: id=%d status=%s is_paused=%s files=%d",
        project_id, status, project.is_paused, len(files),
    )

    if status in (ProjectStatus.COMPLETED.value, ProjectStatus.FAILED.value):
        return

    if project.is_paused:
        logger.debug("orchestrate_project: id=%d is paused, skipping", project_id)
        return

    if status == ProjectStatus.NEW.value:
        await _handle_new(project_id, enqueue_fn)
    elif status == ProjectStatus.DISCOVERING.value:
        await _handle_discovering(project_id, files, enqueue_fn)
    elif status == ProjectStatus.WAITING_FOR_MAPPING.value:
        await _handle_waiting_for_mapping(project_id, files, enqueue_fn)
    elif status == ProjectStatus.PROCESSING.value:
        await _handle_processing(project_id, files, enqueue_fn)
    elif status == ProjectStatus.REVIEW_REQUIRED.value:
        await _handle_review_required(project_id, files, enqueue_fn)


# ------------------------------------------------------------------
# Status handlers
# ------------------------------------------------------------------

async def _handle_new(project_id: int, enqueue_fn: EnqueueFn) -> None:
    logger.info("Project id=%d (new) → enqueueing scan_project", project_id)
    dedupe_key = f"scan_project:{project_id}"
    await enqueue_fn(
        job_type="scan_project",
        project_id=project_id,
        payload={"project_id": project_id},
        dedupe_key=dedupe_key,
    )


async def _handle_discovering(
    project_id: int, files: list[File], enqueue_fn: EnqueueFn,
) -> None:
    # Drive each file in new/discovering state
    discovering = [f for f in files if f.status in (FileStatus.NEW.value, FileStatus.DISCOVERING.value)]
    logger.debug("Project id=%d (discovering): %d file(s) still in discovery", project_id, len(discovering))
    for f in discovering:
        await orchestrate_file(f.id, enqueue_fn)

    # Check if speaker aggregation is needed
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return

        # Count files with extracted subtitles
        files_with_subs = await session.scalar(
            select(func.count())
            .select_from(Subtitle)
            .join(File, Subtitle.file_id == File.id)
            .where(File.project_id == project_id)
        )

        if files_with_subs > 0 and project.speaker_mapping_status == "awaiting_discovery":
            dedupe_key = f"aggregate_speakers:{project_id}"
            await enqueue_fn(
                job_type="aggregate_speakers",
                project_id=project_id,
                payload={"project_id": project_id},
                dedupe_key=dedupe_key,
            )

    # Re-read project state (may have been updated by aggregate_speakers completion)
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id, options=[selectinload(Project.files)])
        if project is None:
            return

        files = list(project.files)

        # Check if all files are past discovery
        any_still_discovering = any(
            f.status in (FileStatus.NEW.value, FileStatus.DISCOVERING.value)
            for f in files
        )

        if any_still_discovering:
            return

        # All files past discovery — decide project transition
        if project.speaker_mapping_status == "mapping_required":
            project.status = ProjectStatus.WAITING_FOR_MAPPING.value
            project.updated_at = datetime.utcnow().isoformat()
            await session.commit()
            logger.info("Project id=%d → waiting_for_mapping", project_id)

            # Set files that need mapping to waiting
            for f in files:
                if f.status in (FileStatus.DISCOVERING.value, FileStatus.NEW.value):
                    f.status = FileStatus.WAITING.value
                    f.blocking_reason = FileBlockingReason.PROJECT_MAPPING_REQUIRED.value
                    f.updated_at = datetime.utcnow().isoformat()
            await session.commit()

        elif project.speaker_mapping_status in ("mapping_complete", "no_speakers"):
            project.status = ProjectStatus.PROCESSING.value
            project.updated_at = datetime.utcnow().isoformat()
            await session.commit()
            logger.info("Project id=%d → processing", project_id)

            # Move discoverable files to ready
            for f in files:
                if f.status == FileStatus.DISCOVERING.value:
                    await orchestrate_file(f.id, enqueue_fn)


async def _handle_waiting_for_mapping(
    project_id: int, files: list[File], enqueue_fn: EnqueueFn,
) -> None:
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return

        if project.speaker_mapping_status != "mapping_complete":
            return  # still waiting

        # Mapping complete → transition to processing
        project.status = ProjectStatus.PROCESSING.value
        project.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        logger.info("Project id=%d → processing (mapping complete)", project_id)

    # Unblock files waiting on mapping
    async with AsyncSessionLocal() as session:
        waiting_files = (await session.scalars(
            select(File).where(
                File.project_id == project_id,
                File.status == FileStatus.WAITING.value,
                File.blocking_reason == FileBlockingReason.PROJECT_MAPPING_REQUIRED.value,
            )
        )).all()
        for f in waiting_files:
            f.status = FileStatus.READY.value
            f.blocking_reason = None
            f.updated_at = datetime.utcnow().isoformat()
        await session.commit()

    # Now drive all files
    for f in files:
        await orchestrate_file(f.id, enqueue_fn)


async def _handle_processing(
    project_id: int, files: list[File], enqueue_fn: EnqueueFn,
) -> None:
    # Drive each non-terminal file
    for f in files:
        if f.status not in _TERMINAL_FILE_STATUSES:
            await orchestrate_file(f.id, enqueue_fn)

    # Re-read to check completion
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id, options=[selectinload(Project.files)])
        if project is None:
            return
        files = list(project.files)

    all_terminal = all(f.status in _TERMINAL_FILE_STATUSES for f in files)
    if not all_terminal:
        return

    any_review = any(f.status == FileStatus.REVIEW_REQUIRED.value for f in files)
    if any_review:
        await _set_project_status(project_id, ProjectStatus.REVIEW_REQUIRED.value)
    else:
        await _set_project_status(project_id, ProjectStatus.COMPLETED.value)


async def _handle_review_required(
    project_id: int, files: list[File], enqueue_fn: EnqueueFn,
) -> None:
    # Re-read files to get current state
    async with AsyncSessionLocal() as session:
        current_files = (await session.scalars(
            select(File).where(File.project_id == project_id)
        )).all()

    any_review = any(f.status == FileStatus.REVIEW_REQUIRED.value for f in current_files)
    if not any_review:
        await _set_project_status(project_id, ProjectStatus.PROCESSING.value)
        # Re-drive files
        for f in current_files:
            if f.status not in _TERMINAL_FILE_STATUSES:
                await orchestrate_file(f.id, enqueue_fn)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _set_project_status(project_id: int, status: str) -> None:
    now = datetime.utcnow().isoformat()
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        old = project.status
        project.status = status
        project.updated_at = now
        await session.commit()
    logger.info("Project id=%d: %s → %s", project_id, old, status)

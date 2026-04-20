from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import SyncSessionLocal
from app.db.models import File, Project
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)


@register_job_handler("scan_project")
def scan_project(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    project_id: int = payload["project_id"]
    now = datetime.utcnow().isoformat()

    progress(0.05, "Loading project")

    with SyncSessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return JobResult(status="failed", result=None,
                             error_code="PROJECT_NOT_FOUND",
                             error_message=f"Project id={project_id} not found")
        source_directory = project.source_directory

    scan_root = (ctx.import_root / source_directory).resolve()
    if not scan_root.is_relative_to(ctx.import_root.resolve()):
        return JobResult(status="failed", result=None,
                         error_code="INVALID_PATH",
                         error_message=f"source_directory '{source_directory}' escapes import root")

    if not scan_root.is_dir():
        return JobResult(status="failed", result=None,
                         error_code="DIRECTORY_NOT_FOUND",
                         error_message=f"Directory not found: {scan_root}")

    progress(0.15, "Scanning for MKV files")

    mkv_files = sorted(scan_root.rglob("*.mkv"))

    progress(0.4, f"Found {len(mkv_files)} MKV files — checking existing records")

    with SyncSessionLocal() as session:
        existing_paths: set[str] = set(
            session.scalars(
                select(File.relative_path).where(File.project_id == project_id)
            ).all()
        )

        new_rows = []
        for mkv in mkv_files:
            relative_path = mkv.relative_to(scan_root).as_posix()
            if relative_path not in existing_paths:
                new_rows.append(dict(
                    project_id=project_id,
                    filename=mkv.name,
                    relative_path=relative_path,
                    status="new",
                    created_at=now,
                    updated_at=now,
                ))

        if new_rows:
            session.execute(
                sqlite_insert(File).on_conflict_do_nothing(
                    index_elements=["project_id", "relative_path"]
                ),
                new_rows,
            )

        project = session.get(Project, project_id)
        project.status = "discovering"
        project.updated_at = now
        session.commit()

    files_created = len(new_rows)
    files_skipped = len(mkv_files) - files_created
    progress(1.0, f"Done — {files_created} new, {files_skipped} skipped")
    return JobResult(
        status="succeeded",
        result={"files_created": files_created, "files_skipped": files_skipped},
        error_code=None,
        error_message=None,
    )

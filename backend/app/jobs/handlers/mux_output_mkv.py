from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import selectinload

from app.core.database import SyncSessionLocal
from app.db.models import File
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)


def _safe_source_path(ctx: JobContext, source_directory: str, relative_path: str) -> Path:
    candidate = (ctx.import_root / source_directory / relative_path).resolve()
    if not candidate.is_relative_to(ctx.import_root.resolve()):
        raise ValueError(f"Resolved path {candidate} escapes import root")
    return candidate


def _safe_output_path(ctx: JobContext, source_directory: str, relative_path: str) -> Path:
    candidate = (ctx.output_root / source_directory / relative_path).resolve()
    if not candidate.is_relative_to(ctx.output_root.resolve()):
        raise ValueError(f"Resolved path {candidate} escapes output root")
    return candidate


@register_job_handler("mux_output_mkv")
def mux_output_mkv(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    now = datetime.utcnow().isoformat()

    progress(0.05, "Loading file record")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id, options=[selectinload(File.project)])
        if file is None:
            return JobResult(status="failed", result=None,
                             error_code="FILE_NOT_FOUND",
                             error_message=f"File id={file_id} not found")
        source_directory = file.project.source_directory
        relative_path = file.relative_path

    try:
        source_path = _safe_source_path(ctx, source_directory, relative_path)
        ass_rel = str(Path(relative_path).with_suffix(".ass"))
        subtitle_path = _safe_output_path(ctx, source_directory, ass_rel)
        output_path = _safe_output_path(ctx, source_directory, relative_path)
    except ValueError as exc:
        return JobResult(status="failed", result=None,
                         error_code="INVALID_PATH", error_message=str(exc))

    if not subtitle_path.exists():
        return JobResult(status="failed", result=None,
                         error_code="SUBTITLE_FILE_MISSING",
                         error_message=f"Subtitle file not found: {subtitle_path}")

    progress(0.15, "Muxing MKV")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    lang_name = ctx.options.target_lang_name or "Unknown"
    lang_code = ctx.options.target_lang_code or "und"

    proc = subprocess.run(
        [
            "mkvmerge",
            "-o", str(output_path),
            str(source_path),
            "--track-name", f"0:{lang_name}",
            "--language", f"0:{lang_code}",
            "--default-track", "0:yes",
            str(subtitle_path),
        ],
        capture_output=True,
    )

    if proc.returncode not in (0, 1):  # mkvmerge exits 1 for warnings
        return JobResult(status="failed", result=None,
                         error_code="MKVMERGE_FAILED",
                         error_message=proc.stderr.decode(errors="replace").strip())

    progress(0.9, "Updating file status")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id)
        file.status = "completed"
        file.completed_at = now
        file.updated_at = now
        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"output_mkv_path": str(output_path)},
        error_code=None,
        error_message=None,
    )

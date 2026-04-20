from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from typing import Any

from sqlalchemy.orm import selectinload

from app.core.database import SyncSessionLocal
from app.db.models import File
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

_ASS_CODEC_IDS = {"S_TEXT/ASS", "S_TEXT/SSA"}


def _safe_source_path(ctx: JobContext, source_directory: str, relative_path: str):
    candidate = (ctx.import_root / source_directory / relative_path).resolve()
    if not candidate.is_relative_to(ctx.import_root.resolve()):
        raise ValueError(f"Resolved path {candidate} escapes import root")
    return candidate


def _pick_subtitle_track(tracks: list[dict]) -> dict | None:
    candidates = [
        t for t in tracks
        if t.get("type") == "subtitles"
        and t.get("properties", {}).get("codec_id") in _ASS_CODEC_IDS
    ]
    if not candidates:
        return None
    for track in candidates:
        props = track.get("properties", {})
        if props.get("language") == "eng" and not props.get("flag_hearing_impaired", False):
            return track
    return candidates[0]


@register_job_handler("inspect_mkv")
def inspect_mkv(
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
    except ValueError as exc:
        return JobResult(status="failed", result=None,
                         error_code="INVALID_PATH", error_message=str(exc))

    progress(0.2, "Running mkvmerge inspection")

    proc = subprocess.run(
        ["mkvmerge", "-J", str(source_path)],
        capture_output=True,
    )
    if proc.returncode != 0:
        return JobResult(status="failed", result=None,
                         error_code="MKVMERGE_FAILED",
                         error_message=proc.stderr.decode(errors="replace").strip())

    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return JobResult(status="failed", result=None,
                         error_code="MKVMERGE_PARSE_ERROR",
                         error_message=str(exc))

    progress(0.7, "Selecting subtitle track")

    best = _pick_subtitle_track(info.get("tracks", []))
    if best is None:
        with SyncSessionLocal() as session:
            file = session.get(File, file_id)
            file.status = "failed"
            file.blocking_reason = "subtitle_missing"
            file.updated_at = now
            session.commit()
        return JobResult(status="failed", result=None,
                         error_code="subtitle_missing",
                         error_message="No ASS/SSA subtitle track found in file")

    track_id: int = best["id"]

    progress(0.9, "Saving result")

    with SyncSessionLocal() as session:
        file = session.get(File, file_id)
        file.subtitle_track_index = track_id
        file.detected_subtitle_format = "ass"
        file.status = "discovering"
        file.updated_at = now
        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"subtitle_track_index": track_id, "format": "ass"},
        error_code=None,
        error_message=None,
    )

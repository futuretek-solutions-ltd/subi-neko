from __future__ import annotations

import json
import logging
import re
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

# Releases commonly ship two English ASS tracks — a signs/songs typesetting
# track and the full dialogue track — in that order (e.g. Judas:
# "English [Signs-Songs]" then "English [Full]"). Picking the first eng track
# silently yields a file with zero dialogue events, so the track *name* has to
# be part of the decision.
_SIGNS_TRACK_NAME_RE = re.compile(r"sign|song|karaoke|lyric|typeset|forced", re.IGNORECASE)
_FULL_TRACK_NAME_RE = re.compile(r"\bfull\b|dialog", re.IGNORECASE)


def _safe_source_path(ctx: JobContext, source_directory: str, relative_path: str):
    candidate = (ctx.import_root / source_directory / relative_path).resolve()
    if not candidate.is_relative_to(ctx.import_root.resolve()):
        raise ValueError(f"Resolved path {candidate} escapes import root")
    return candidate


def _track_rank(track: dict) -> tuple:
    """Sort key for subtitle track preference — lower is better.

    Lexicographic so each signal only breaks ties left by the ones above it:
    language first (this pipeline expects an English source), then avoid
    signs/songs tracks, then hearing-impaired and forced flags, then prefer an
    explicit "Full"/"Dialogue" name, and finally keep the file's own order.
    """
    props = track.get("properties", {})
    name = props.get("track_name") or ""
    return (
        props.get("language") != "eng",
        bool(_SIGNS_TRACK_NAME_RE.search(name)),
        bool(props.get("flag_hearing_impaired", False)),
        bool(props.get("forced_track", False)),
        not _FULL_TRACK_NAME_RE.search(name),
        track.get("id", 0),
    )


def _ass_subtitle_tracks(tracks: list[dict]) -> list[dict]:
    return [
        t for t in tracks
        if t.get("type") == "subtitles"
        and t.get("properties", {}).get("codec_id") in _ASS_CODEC_IDS
    ]


def _pick_subtitle_track(tracks: list[dict]) -> dict | None:
    candidates = _ass_subtitle_tracks(tracks)
    if not candidates:
        return None
    return min(candidates, key=_track_rank)


def _describe_candidates(tracks: list[dict]) -> list[dict]:
    """Every ASS candidate, recorded in the job result so a mis-picked track
    stays diagnosable after the fact."""
    return [
        {
            "id": t.get("id"),
            "language": t.get("properties", {}).get("language"),
            "track_name": t.get("properties", {}).get("track_name"),
        }
        for t in sorted(_ass_subtitle_tracks(tracks), key=_track_rank)
    ]


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

    all_tracks = info.get("tracks", [])
    best = _pick_subtitle_track(all_tracks)
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
        result={
            "subtitle_track_index": track_id,
            "format": "ass",
            "track_name": best.get("properties", {}).get("track_name"),
            "candidates": _describe_candidates(all_tracks),
        },
        error_code=None,
        error_message=None,
    )

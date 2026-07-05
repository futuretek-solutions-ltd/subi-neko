from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import SyncSessionLocal
from app.db.models import File, Project, ProjectSpeaker, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler
from app.subs.tag_masking import plain_text

logger = logging.getLogger(__name__)

_SAMPLES_PER_SPEAKER = 5


def _sample_spread(lines: list[str], count: int) -> list[str]:
    if len(lines) <= count:
        return lines
    step = len(lines) / count
    return [lines[int(i * step)] for i in range(count)]


@register_job_handler("aggregate_speakers")
def aggregate_speakers(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    """Collect distinct speaker names across the project, with per-speaker
    line counts and sample dialogue lines for the mapping-inference job.
    Ends with speaker_mapping_status='aggregated' (or 'complete' when there
    is nothing to map) — infer_character_mapping takes it from there."""
    project_id: int = payload["project_id"]
    now = datetime.utcnow().isoformat()

    progress(0.1, "Scanning subtitle events for speaker names")

    with SyncSessionLocal() as session:
        rows = session.execute(
            select(SubtitleEvent.name, SubtitleEvent.source_text)
            .join(File, SubtitleEvent.file_id == File.id)
            .where(
                File.project_id == project_id,
                SubtitleEvent.event_type == "dialogue",
                SubtitleEvent.name.isnot(None),
                SubtitleEvent.name != "",
            )
            .order_by(SubtitleEvent.file_id, SubtitleEvent.line_index)
        ).all()

        total_dialogue_count: int = session.scalar(
            select(func.count(SubtitleEvent.id))
            .join(File, SubtitleEvent.file_id == File.id)
            .where(
                File.project_id == project_id,
                SubtitleEvent.event_type == "dialogue",
            )
        ) or 0

    lines_by_speaker: dict[str, list[str]] = {}
    for name, source_text in rows:
        text = plain_text(source_text)
        lines_by_speaker.setdefault(name, [])
        if text:
            lines_by_speaker[name].append(text)

    named_dialogue_count = len(rows)
    coverage = (named_dialogue_count / total_dialogue_count) if total_dialogue_count > 0 else 0.0

    progress(0.5, f"Upserting {len(lines_by_speaker)} speaker(s)")

    created = 0
    with SyncSessionLocal() as session:
        for name, lines in lines_by_speaker.items():
            samples = _sample_spread(lines, _SAMPLES_PER_SPEAKER)
            stmt = (
                sqlite_insert(ProjectSpeaker)
                .values(
                    project_id=project_id,
                    name=name,
                    line_count=len(lines),
                    sample_lines_json=json.dumps(samples, ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["project_id", "name"],
                    set_={
                        "line_count": len(lines),
                        "sample_lines_json": json.dumps(samples, ensure_ascii=False),
                        "updated_at": now,
                    },
                )
            )
            result = session.execute(stmt)
            if result.rowcount > 0:
                created += 1

        project = session.get(Project, project_id)
        if project is not None:
            project.speaker_coverage = coverage
            if lines_by_speaker:
                project.speaker_mapping_status = "aggregated"
            else:
                # Nothing to map — inference would be a no-op.
                project.speaker_mapping_status = "complete"
            project.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "speakers_created": created,
            "speakers_total": len(lines_by_speaker),
            "speaker_coverage": coverage,
        },
        error_code=None,
        error_message=None,
    )

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import SyncSessionLocal
from app.db.models import File, Project, ProjectSpeaker, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)


@register_job_handler("aggregate_speakers")
def aggregate_speakers(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    project_id: int = payload["project_id"]
    now = datetime.utcnow().isoformat()

    progress(0.1, "Scanning subtitle events for speaker names")

    with SyncSessionLocal() as session:
        rows = session.execute(
            select(distinct(SubtitleEvent.name))
            .join(File, SubtitleEvent.file_id == File.id)
            .where(
                File.project_id == project_id,
                SubtitleEvent.name.isnot(None),
                SubtitleEvent.name != "",
            )
        )
        names: list[str] = [row[0] for row in rows.all()]

    progress(0.5, f"Inserting {len(names)} speaker(s)")

    created = 0
    with SyncSessionLocal() as session:
        for name in names:
            stmt = (
                sqlite_insert(ProjectSpeaker)
                .values(project_id=project_id, name=name, created_at=now, updated_at=now)
                .on_conflict_do_nothing(index_elements=["project_id", "name"])
            )
            result = session.execute(stmt)
            if result.rowcount > 0:
                created += 1

        project = session.get(Project, project_id)
        if project is not None:
            project.speaker_mapping_status = "mapping_required"
            project.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"speakers_created": created, "speakers_total": len(names)},
        error_code=None,
        error_message=None,
    )

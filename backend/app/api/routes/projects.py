import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.db.models import (
    File,
    FileBlockingReason,
    FileStatus,
    JobRecord,
    Project,
    ProjectCharacter,
    ProjectSpeaker,
    ProjectStatus,
    QaItem,
    SpeakerCharacterMapping,
    SubtitleChunk,
    SubtitleEvent,
)
from app.jobs.manager import job_manager
from app.metadata.base import CharacterGender
from app.orchestrator.file_orchestrator import orchestrate_file
from app.orchestrator.project_orchestrator import orchestrate_project

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    name: str
    source_directory: str
    anime_provider: str
    anime_external_id: str
    speaker_mapping_status: str
    status: str
    is_paused: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class FileOut(BaseModel):
    id: int
    project_id: int
    filename: str
    relative_path: str
    status: str
    blocking_reason: str | None
    detected_subtitle_format: str | None
    subtitle_track_index: int | None
    retry_count: int
    last_error_code: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    chunks_total: int | None = None
    chunks_done: int | None = None
    qa_issues: int = 0
    qa_errors: int = 0
    qa_warnings: int = 0

    model_config = {"from_attributes": True}


class CharacterOut(BaseModel):
    id: int
    project_id: int
    external_id: str | None
    name: str
    role: str | None
    gender: CharacterGender | None
    social_position: str | None
    aliases: str | None
    note: str | None
    created_at: str
    updated_at: str
    speaker_ids: list[int]

    model_config = {"from_attributes": True}


class CharacterUpdateIn(BaseModel):
    gender: CharacterGender | None = None
    note: str | None = None
    speaker_ids: list[int] = []


class SpeakerOut(BaseModel):
    id: int
    project_id: int
    name: str
    created_at: str
    updated_at: str
    mapping_count: int

    model_config = {"from_attributes": True}


class QaIssueOut(BaseModel):
    id: int
    severity: str
    qa_type: str
    message: str
    details_json: str | None
    created_at: str

    model_config = {"from_attributes": True}


class SubtitleEventEditorOut(BaseModel):
    id: int
    file_id: int
    line_index: int
    event_type: str
    source_text: str
    translated_text: str | None
    original_ai_translated_text: str | None
    is_user_edited: bool
    is_locked: bool
    is_approved: bool
    issues: list[QaIssueOut]

    model_config = {"from_attributes": True}


class SubtitleEventUpdateIn(BaseModel):
    translated_text: str | None = None


@router.get("", response_model=list[ProjectOut])
async def list_projects():
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(select(Project).order_by(Project.name))
        return list(rows.all())


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project


@router.post("/{project_id}/pause", response_model=ProjectOut)
async def pause_project(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.status in (ProjectStatus.COMPLETED.value, ProjectStatus.FAILED.value):
            raise HTTPException(status_code=409, detail=f"Cannot pause a project with status '{project.status}'")
        if not project.is_paused:
            project.is_paused = True
            project.updated_at = datetime.utcnow().isoformat()
            await session.commit()
        await session.refresh(project)

    await job_manager.cancel_queued_project_jobs(project_id)
    return project


@router.post("/{project_id}/resume", response_model=ProjectOut)
async def resume_project(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if not project.is_paused:
            return project
        project.is_paused = False
        project.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(project)

    await orchestrate_project(project_id, job_manager.enqueue)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

    # Cancel all active jobs before deletion so workers don't race against CASCADE
    await job_manager.cancel_project_jobs(project_id)

    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is not None:
            await session.delete(project)
            await session.commit()


@router.get("/{project_id}/files", response_model=list[FileOut])
async def list_project_files(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        rows = await session.scalars(
            select(File)
            .where(File.project_id == project_id)
            .order_by(File.filename)
        )
        files = list(rows.all())

        # Fetch chunk counts for all files in one query
        file_ids = [f.id for f in files]
        chunk_rows = (await session.execute(
            select(
                SubtitleChunk.file_id,
                func.count().label("total"),
                func.sum(case((SubtitleChunk.status != "pending", 1), else_=0)).label("done"),
            )
            .where(SubtitleChunk.file_id.in_(file_ids))
            .group_by(SubtitleChunk.file_id)
        )).all() if file_ids else []

        chunk_map = {row.file_id: (int(row.done or 0), int(row.total)) for row in chunk_rows}

        qa_rows = (await session.execute(
            select(
                QaItem.file_id,
                QaItem.severity,
                func.count().label("cnt"),
            )
            .where(QaItem.file_id.in_(file_ids))
            .where(QaItem.is_resolved == 0)
            .group_by(QaItem.file_id, QaItem.severity)
        )).all() if file_ids else []
        qa_map: dict[int, dict[str, int]] = {}
        for row in qa_rows:
            bucket = "errors" if _severity_rank(row.severity) <= 1 else "warnings"
            qa_map.setdefault(row.file_id, {"errors": 0, "warnings": 0})[bucket] += int(row.cnt or 0)

        result = []
        for f in files:
            out = FileOut.model_validate(f)
            if f.id in chunk_map:
                out.chunks_done, out.chunks_total = chunk_map[f.id]
            qa_counts = qa_map.get(f.id, {"errors": 0, "warnings": 0})
            out.qa_errors = qa_counts["errors"]
            out.qa_warnings = qa_counts["warnings"]
            out.qa_issues = out.qa_errors + out.qa_warnings
            result.append(out)
        return result


class ChunkJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    attempt_count: int
    result: dict | None = None
    error_code: str | None
    error_message: str | None
    scheduled_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str

    model_config = {"from_attributes": True}


class ChunkOut(BaseModel):
    id: int
    chunk_index: int
    translate_from_line: int
    translate_to_line: int
    status: str
    model: str | None
    llm_review_needed: bool
    retry_count: int = 0
    repair_attempt_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    failed_job_type: str | None = None
    qa_errors: int = 0
    qa_warnings: int = 0
    jobs: dict[str, ChunkJobOut] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


CHUNK_PIPELINE_JOB_TYPES = {
    "translate_chunk",
    "validate_chunk",
    "repair_chunk",
    "review_chunk_rules",
    "review_chunk_grammar",
    "review_chunk_languagetool",
    "review_chunk_llm",
}


def _job_chunk_index(job: JobRecord) -> int | None:
    try:
        payload = json.loads(job.payload_json or "{}")
    except json.JSONDecodeError:
        return None
    value = payload.get("chunk_index")
    return value if isinstance(value, int) else None


def _job_result(job: JobRecord) -> dict | None:
    if not job.result_json:
        return None
    try:
        value = json.loads(job.result_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


@router.get("/{project_id}/files/{file_id}/chunks", response_model=list[ChunkOut])
async def list_file_chunks(project_id: int, file_id: int):
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        chunks = list((await session.scalars(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .order_by(SubtitleChunk.chunk_index)
        )).all())

        # Aggregate unresolved QA items by line_index and severity in one query
        qa_rows = (await session.execute(
            select(
                SubtitleEvent.line_index,
                QaItem.severity,
                func.count().label("cnt"),
            )
            .join(QaItem, QaItem.subtitle_event_id == SubtitleEvent.id)
            .where(SubtitleEvent.file_id == file_id)
            .where(QaItem.is_resolved == 0)
            .group_by(SubtitleEvent.line_index, QaItem.severity)
        )).all()

        # Build line_index → {severity: count} map
        qa_by_line: dict[int, dict[str, int]] = {}
        for row in qa_rows:
            qa_by_line.setdefault(row.line_index, {})[row.severity] = int(row.cnt)

        job_rows = list((await session.scalars(
            select(JobRecord)
            .where(JobRecord.file_id == file_id)
            .where(JobRecord.job_type.in_(CHUNK_PIPELINE_JOB_TYPES))
            .order_by(JobRecord.updated_at)
        )).all())

        jobs_by_chunk: dict[int, dict[str, ChunkJobOut]] = {}
        for job in job_rows:
            chunk_index = _job_chunk_index(job)
            if chunk_index is None:
                continue
            jobs_by_chunk.setdefault(chunk_index, {})[job.job_type] = ChunkJobOut(
                id=job.id,
                job_type=job.job_type,
                status=job.status,
                attempt_count=job.attempt_count,
                result=_job_result(job),
                error_code=job.error_code,
                error_message=job.error_message,
                scheduled_at=job.scheduled_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                updated_at=job.updated_at,
            )

        result = []
        for chunk in chunks:
            errors = warnings = 0
            for line_idx, sevs in qa_by_line.items():
                if chunk.translate_from_line <= line_idx <= chunk.translate_to_line:
                    errors += sevs.get("error", 0)
                    warnings += sevs.get("warning", 0)
            result.append(ChunkOut(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                translate_from_line=chunk.translate_from_line,
                translate_to_line=chunk.translate_to_line,
                status=chunk.status,
                model=chunk.model,
                llm_review_needed=bool(chunk.llm_review_needed),
                retry_count=chunk.retry_count or 0,
                repair_attempt_count=chunk.repair_attempt_count or 0,
                last_error_code=chunk.last_error_code,
                last_error_message=chunk.last_error_message,
                failed_job_type=chunk.failed_job_type,
                qa_errors=errors,
                qa_warnings=warnings,
                jobs=jobs_by_chunk.get(chunk.chunk_index, {}),
            ))
        return result


# Status to restore when retrying a job_failed chunk, keyed by failed_job_type.
_RETRY_STATUS_BY_JOB_TYPE: dict[str, str] = {
    "translate_chunk":    "pending",
    "validate_chunk":     "translated",
    "repair_chunk":       "validate_trans_failed",
    "review_chunk_rules": "validated",
    "review_chunk_grammar": "rules_reviewed",
    "review_chunk_llm":   "grammar_reviewed",
}


@router.post("/{project_id}/files/{file_id}/chunks/{chunk_index}/retry", response_model=ChunkOut)
async def retry_chunk(project_id: int, file_id: int, chunk_index: int):
    """Retry a chunk that is in job_failed or validate_repair_failed state."""
    now = datetime.utcnow().isoformat()

    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        chunk = await session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found")

        if chunk.status not in ("job_failed", "validate_repair_failed"):
            raise HTTPException(
                status_code=409,
                detail=f"Chunk is not in a retryable state (current: {chunk.status})",
            )

        if chunk.status == "job_failed":
            failed_job_type = chunk.failed_job_type
            restore_status = _RETRY_STATUS_BY_JOB_TYPE.get(failed_job_type or "")
            if restore_status is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot determine retry status for failed_job_type={failed_job_type!r}",
                )
            chunk.status = restore_status
        else:
            # validate_repair_failed: reset repair count and go back to translated
            chunk.status = "translated"
            chunk.repair_attempt_count = 0

        chunk.retry_count = 0
        chunk.last_error_code = None
        chunk.last_error_message = None
        chunk.failed_job_type = None
        chunk.updated_at = now

        # If file was put into waiting due to this chunk, restore it to processing.
        if file.status == "waiting" and file.blocking_reason in (
            FileBlockingReason.TRANSLATION_FAILED.value,
            FileBlockingReason.VALIDATION_FAILED.value,
        ):
            file.status = FileStatus.PROCESSING.value
            file.blocking_reason = None
            file.updated_at = now

        await session.commit()
        await session.refresh(chunk)

    await orchestrate_file(file_id, job_manager.enqueue)
    return ChunkOut(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        translate_from_line=chunk.translate_from_line,
        translate_to_line=chunk.translate_to_line,
        status=chunk.status,
        model=chunk.model,
        llm_review_needed=bool(chunk.llm_review_needed),
        retry_count=chunk.retry_count or 0,
        repair_attempt_count=chunk.repair_attempt_count or 0,
        last_error_code=chunk.last_error_code,
        last_error_message=chunk.last_error_message,
        failed_job_type=chunk.failed_job_type,
        qa_errors=0,
        qa_warnings=0,
    )


def _severity_rank(severity: str) -> int:
    return {
        "critical": 0,
        "error": 1,
        "high": 1,
        "warning": 2,
        "medium": 2,
        "info": 3,
        "low": 3,
    }.get(severity.lower(), 99)


def _subtitle_event_editor_out(event: SubtitleEvent) -> SubtitleEventEditorOut:
    issues = sorted(
        [item for item in event.qa_items if not item.is_resolved],
        key=lambda item: (_severity_rank(item.severity), item.created_at, item.id),
    )
    return SubtitleEventEditorOut(
        id=event.id,
        file_id=event.file_id,
        line_index=event.line_index,
        event_type=event.event_type,
        source_text=event.source_text,
        translated_text=event.translated_text,
        original_ai_translated_text=event.original_ai_translated_text,
        is_user_edited=bool(event.is_user_edited),
        is_locked=bool(event.is_locked),
        is_approved=bool(event.is_approved),
        issues=[QaIssueOut.model_validate(item) for item in issues],
    )


@router.get("/{project_id}/files/{file_id}/subtitle-events", response_model=list[SubtitleEventEditorOut])
async def list_file_subtitle_events(project_id: int, file_id: int):
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        events = list((await session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .options(selectinload(SubtitleEvent.qa_items))
            .order_by(SubtitleEvent.line_index)
        )).all())

        return [_subtitle_event_editor_out(event) for event in events]


@router.put("/{project_id}/files/{file_id}/subtitle-events/{event_id}", response_model=SubtitleEventEditorOut)
async def update_file_subtitle_event(
    project_id: int,
    file_id: int,
    event_id: int,
    body: SubtitleEventUpdateIn,
):
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        event = await session.get(
            SubtitleEvent,
            event_id,
            options=[selectinload(SubtitleEvent.qa_items)],
        )
        if event is None or event.file_id != file_id:
            raise HTTPException(status_code=404, detail="Subtitle event not found")

        event.translated_text = body.translated_text
        event.is_user_edited = 0 if body.translated_text == event.original_ai_translated_text else 1
        event.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(event, ["qa_items"])
        return _subtitle_event_editor_out(event)


@router.post("/{project_id}/files/{file_id}/subtitle-events/{event_id}/revert", response_model=SubtitleEventEditorOut)
async def revert_file_subtitle_event(
    project_id: int,
    file_id: int,
    event_id: int,
):
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        event = await session.get(
            SubtitleEvent,
            event_id,
            options=[selectinload(SubtitleEvent.qa_items)],
        )
        if event is None or event.file_id != file_id:
            raise HTTPException(status_code=404, detail="Subtitle event not found")
        if event.original_ai_translated_text is None:
            raise HTTPException(status_code=409, detail="No original AI translation stored")

        event.translated_text = event.original_ai_translated_text
        event.is_user_edited = 0
        event.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(event, ["qa_items"])
        return _subtitle_event_editor_out(event)


@router.post("/{project_id}/files/{file_id}/qa-issues/{issue_id}/resolve", response_model=SubtitleEventEditorOut)
async def resolve_file_qa_issue(project_id: int, file_id: int, issue_id: int):
    async with AsyncSessionLocal() as session:
        file = await session.get(File, file_id)
        if file is None or file.project_id != project_id:
            raise HTTPException(status_code=404, detail="File not found")

        issue = await session.get(QaItem, issue_id)
        if issue is None or issue.file_id != file_id:
            raise HTTPException(status_code=404, detail="QA issue not found")

        issue.is_resolved = 1
        issue.resolved_at = datetime.utcnow().isoformat()
        await session.commit()

        if issue.subtitle_event_id is None:
            raise HTTPException(status_code=404, detail="QA issue has no subtitle event")

        event = await session.get(
            SubtitleEvent,
            issue.subtitle_event_id,
            options=[selectinload(SubtitleEvent.qa_items)],
        )
        if event is None:
            raise HTTPException(status_code=404, detail="Subtitle event not found")
        out = _subtitle_event_editor_out(event)

    await orchestrate_file(file_id, job_manager.enqueue)
    return out


@router.get("/{project_id}/characters", response_model=list[CharacterOut])
async def list_project_characters(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        rows = await session.scalars(
            select(ProjectCharacter)
            .where(ProjectCharacter.project_id == project_id)
            .options(selectinload(ProjectCharacter.speaker_mappings))
            .order_by(ProjectCharacter.name)
        )
        characters = list(rows.all())
        result = []
        for char in characters:
            result.append(CharacterOut(
                **{c: getattr(char, c) for c in [
                    "id", "project_id", "external_id", "name", "role",
                    "gender", "social_position", "aliases", "note",
                    "created_at", "updated_at",
                ]},
                speaker_ids=[m.project_speaker_id for m in char.speaker_mappings],
            ))
        return result


@router.get("/{project_id}/speakers", response_model=list[SpeakerOut])
async def list_project_speakers(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        rows = await session.scalars(
            select(ProjectSpeaker)
            .where(ProjectSpeaker.project_id == project_id)
            .options(selectinload(ProjectSpeaker.character_mappings))
            .order_by(ProjectSpeaker.name)
        )
        speakers = list(rows.all())
        return [
            SpeakerOut(
                **{c: getattr(s, c) for c in [
                    "id", "project_id", "name", "created_at", "updated_at",
                ]},
                mapping_count=len(s.character_mappings),
            )
            for s in speakers
        ]


@router.put("/{project_id}/characters/{character_id}", response_model=CharacterOut)
async def update_project_character(
    project_id: int, character_id: int, body: CharacterUpdateIn
):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        char = await session.get(
            ProjectCharacter, character_id,
            options=[selectinload(ProjectCharacter.speaker_mappings)],
        )
        if char is None or char.project_id != project_id:
            raise HTTPException(status_code=404, detail="Character not found")

        # Validate all provided speaker IDs belong to this project
        deduped_speaker_ids = list(dict.fromkeys(body.speaker_ids))
        if deduped_speaker_ids:
            valid_speakers = await session.scalars(
                select(ProjectSpeaker)
                .where(
                    ProjectSpeaker.id.in_(deduped_speaker_ids),
                    ProjectSpeaker.project_id == project_id,
                )
            )
            valid_ids = {s.id for s in valid_speakers.all()}
            invalid = set(deduped_speaker_ids) - valid_ids
            if invalid:
                raise HTTPException(
                    status_code=422,
                    detail=f"Speaker IDs not found in project: {sorted(invalid)}",
                )

        # Update scalar fields — only overwrite what was explicitly sent
        update_data = body.model_dump(exclude_unset=True)
        if "gender" in update_data:
            char.gender = update_data["gender"]
        if "social_position" in update_data:
            char.social_position = update_data["social_position"]
        if "note" in update_data:
            char.note = update_data["note"]
        char.updated_at = datetime.utcnow().isoformat()

        # Replace speaker mappings
        for mapping in list(char.speaker_mappings):
            await session.delete(mapping)
        await session.flush()

        for sid in deduped_speaker_ids:
            session.add(SpeakerCharacterMapping(
                project_speaker_id=sid,
                character_id=character_id,
            ))

        await session.commit()
        await session.refresh(char, ["speaker_mappings"])

        return CharacterOut(
            **{c: getattr(char, c) for c in [
                "id", "project_id", "external_id", "name", "role",
                "gender", "social_position", "aliases", "note",
                "created_at", "updated_at",
            ]},
            speaker_ids=[m.project_speaker_id for m in char.speaker_mappings],
        )


class ProjectStatsOut(BaseModel):
    qa_errors: int
    qa_warnings: int


@router.get("/{project_id}/stats", response_model=ProjectStatsOut)
async def get_project_stats(project_id: int):
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(
                func.sum(case((QaItem.severity == "error", 1), else_=0)).label("errors"),
                func.sum(case((QaItem.severity == "warning", 1), else_=0)).label("warnings"),
            )
            .join(File, QaItem.file_id == File.id)
            .where(File.project_id == project_id, QaItem.is_resolved == 0)
        )).one()
        return ProjectStatsOut(
            qa_errors=int(row.errors or 0),
            qa_warnings=int(row.warnings or 0),
        )


@router.post("/{project_id}/complete-mapping", response_model=ProjectOut)
async def complete_mapping(project_id: int):
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.status != ProjectStatus.WAITING_FOR_MAPPING.value:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot complete mapping for project in status '{project.status}'",
            )
        project.speaker_mapping_status = "mapping_complete"
        project.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(project)

    await orchestrate_project(project_id, job_manager.enqueue)
    return project

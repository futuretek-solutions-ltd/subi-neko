"""Derived translation-context readiness for the project-level quality gate.

Everything here is computed from current DB state on demand — there is no
stored "context status" column (the two user inputs, Project.context_approved_at
and File.translation_requested_at, are the only persisted gate state). The
same computation backs both the GET /projects/{id}/context-status endpoint and
the project orchestrator's discovering → context_review exit condition, so the
two can never disagree.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.db import options as options_store
from app.db.models import (
    File,
    FileBlockingReason,
    FileStatus,
    JobRecord,
    JobStatus,
    Project,
    ProjectAddressPair,
    ProjectCharacter,
    ProjectCharacterStyle,
    ProjectGlossaryTerm,
    ProjectSpeaker,
    ProjectStyleBible,
)

# Blocking reasons that mean "this file will never deliver subtitles"
_NO_SUBS_REASONS = (
    FileBlockingReason.SUBTITLE_MISSING.value,
    FileBlockingReason.SUBTITLE_PARSE_FAILED.value,
)

# An unmapped non-extra speaker with at least this many lines drags the
# overall confidence to "low" on its own.
_MAJOR_SPEAKER_LINES = 50


async def compute_context_status(project_id: int) -> dict[str, Any] | None:
    """Full readiness snapshot for the translation-context gate, or None if
    the project doesn't exist."""
    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return None

        files = (await session.scalars(
            select(File).where(File.project_id == project_id)
        )).all()
        speakers = (await session.scalars(
            select(ProjectSpeaker)
            .options(selectinload(ProjectSpeaker.character))
            .where(ProjectSpeaker.project_id == project_id)
        )).all()
        bible_version = await session.scalar(
            select(func.max(ProjectStyleBible.version))
            .where(ProjectStyleBible.project_id == project_id)
        )
        bible_user_edited = False
        if bible_version is not None:
            bible_user_edited = bool(await session.scalar(
                select(ProjectStyleBible.is_user_edited).where(
                    ProjectStyleBible.project_id == project_id,
                    ProjectStyleBible.version == bible_version,
                )
            ))
        glossary_total = await session.scalar(
            select(func.count()).select_from(ProjectGlossaryTerm)
            .where(ProjectGlossaryTerm.project_id == project_id,
                   ProjectGlossaryTerm.is_active == 1)
        )
        glossary_locked = await session.scalar(
            select(func.count()).select_from(ProjectGlossaryTerm)
            .where(ProjectGlossaryTerm.project_id == project_id,
                   ProjectGlossaryTerm.is_active == 1,
                   ProjectGlossaryTerm.locked == 1)
        )
        address_pairs = await session.scalar(
            select(func.count()).select_from(ProjectAddressPair)
            .where(ProjectAddressPair.project_id == project_id)
        )
        character_styles = await session.scalar(
            select(func.count()).select_from(ProjectCharacterStyle)
            .join(ProjectCharacter,
                  ProjectCharacterStyle.project_character_id == ProjectCharacter.id)
            .where(ProjectCharacter.project_id == project_id)
        )
        characters_total = await session.scalar(
            select(func.count()).select_from(ProjectCharacter)
            .where(ProjectCharacter.project_id == project_id)
        )

        jobs: dict[str, JobRecord] = {}
        for key in (
            f"aggregate_speakers:{project_id}",
            f"infer_character_mapping:{project_id}",
            f"generate_style_bible:{project_id}",
        ):
            record = await session.scalar(
                select(JobRecord).where(JobRecord.dedupe_key == key)
            )
            if record is not None:
                jobs[key.split(":", 1)[0]] = record

    require_bible = (
        (await options_store.aget("REQUIRE_STYLE_BIBLE", "1") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    threshold_raw = await options_store.aget("AUTO_MAPPING_ACCEPT_THRESHOLD", "0.8")
    try:
        threshold = float(threshold_raw or 0.8)
    except ValueError:
        threshold = 0.8

    # --- discovery ---------------------------------------------------------
    files_total = len(files)
    still_discovering = sum(
        1 for f in files
        if f.status in (FileStatus.NEW.value, FileStatus.DISCOVERING.value)
    )
    files_missing_subs = sum(1 for f in files if f.blocking_reason in _NO_SUBS_REASONS)
    if files_total == 0:
        discovery_status = "pending"
    elif still_discovering > 0:
        discovery_status = "running"
    else:
        discovery_status = "complete"
    discovery = {
        "key": "discovery",
        "status": discovery_status,
        "detail": {
            "files_total": files_total,
            "files_discovered": files_total - still_discovering,
            "files_missing_subs": files_missing_subs,
        },
    }

    # --- speaker aggregation / character mapping / style bible -------------
    mapping_status = project.speaker_mapping_status
    aggregation = _job_backed_component(
        "speaker_aggregation",
        complete=mapping_status in ("aggregated", "complete"),
        job=jobs.get("aggregate_speakers"),
        detail={
            "speakers_total": len(speakers),
            "extras": sum(1 for s in speakers if s.is_extra),
        },
    )
    mapping = _job_backed_component(
        "character_mapping",
        complete=mapping_status == "complete",
        job=jobs.get("infer_character_mapping"),
        detail=_mapping_detail(speakers, threshold, characters_total or 0),
    )
    bible = _job_backed_component(
        "style_bible",
        complete=bible_version is not None,
        job=jobs.get("generate_style_bible"),
        detail={
            "version": bible_version,
            "is_user_edited": bible_user_edited,
            "enabled": require_bible,
        },
    )
    if not require_bible and bible_version is None:
        bible["status"] = "skipped"
        bible.pop("error_code", None)
        bible.pop("error_message", None)

    gating = [discovery, aggregation, mapping, bible]
    info = [
        {"key": "glossary", "status": "info",
         "detail": {"terms": glossary_total or 0, "locked": glossary_locked or 0}},
        {"key": "address_pairs", "status": "info", "detail": {"pairs": address_pairs or 0}},
        {"key": "character_styles", "status": "info", "detail": {"count": character_styles or 0}},
    ]

    attention = _attention_items(speakers, threshold)
    if (characters_total or 0) == 0 and any(not s.is_extra for s in speakers):
        # Surfaced first: without a roster there are no genders and no
        # mapping — the user should know the provider returned nothing
        # before approving the context.
        attention.insert(0, {
            "type": "empty_character_roster",
            "message": ("Metadata provider returned no characters — speaker "
                        "genders are unknown and character mapping was skipped."),
        })
    confidence = _confidence(speakers, threshold)

    if project.context_approved_at:
        state = "approved"
    elif any(c["status"] == "failed" for c in gating):
        state = "failed"
    elif all(c["status"] in ("complete", "skipped") for c in gating):
        state = "ready_for_review"
    else:
        state = "building"

    return {
        "state": state,
        "approved_at": project.context_approved_at,
        "components": gating + info,
        "attention": attention,
        "confidence": confidence,
    }


def _job_backed_component(
    key: str,
    complete: bool,
    job: JobRecord | None,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """Data presence wins; otherwise the component reflects its job's state."""
    component: dict[str, Any] = {"key": key, "detail": detail}
    if complete:
        component["status"] = "complete"
    elif job is not None and job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        component["status"] = "running"
    elif job is not None and job.status == JobStatus.FAILED.value:
        component["status"] = "failed"
        component["error_code"] = job.error_code
        component["error_message"] = job.error_message
        component["retryable"] = True
    else:
        component["status"] = "pending"
    return component


def _mapping_detail(
    speakers: list[ProjectSpeaker], threshold: float, characters_total: int,
) -> dict[str, Any]:
    non_extra = [s for s in speakers if not s.is_extra]
    return {
        "mapped": sum(1 for s in non_extra if s.character_id is not None),
        "unmapped_non_extra": sum(
            1 for s in non_extra
            if s.character_id is None and s.match_origin != "manual"
        ),
        "manual": sum(1 for s in speakers if s.match_origin == "manual"),
        "below_threshold": sum(
            1 for s in non_extra
            if s.character_id is not None
            and s.match_origin != "manual"
            and (s.match_confidence or 0.0) < threshold
        ),
        "characters_total": characters_total,
        # With no roster the mapping stage had nothing to match against —
        # "complete" then means "skipped", not "everything is mapped".
        "roster_empty": characters_total == 0,
    }


def _attention_items(speakers: list[ProjectSpeaker], threshold: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for s in speakers:
        if s.is_extra or s.match_origin == "manual":
            continue
        if s.character_id is None:
            items.append({
                "type": "unmapped_speaker",
                "speaker_id": s.id,
                "name": s.name,
                "line_count": s.line_count or 0,
            })
        elif (s.match_confidence or 0.0) < threshold:
            items.append({
                "type": "low_confidence_mapping",
                "speaker_id": s.id,
                "name": s.name,
                "line_count": s.line_count or 0,
                "confidence": s.match_confidence,
                "character_name": s.character.name if s.character else None,
            })
    items.sort(key=lambda item: -item["line_count"])
    return items


def _confidence(speakers: list[ProjectSpeaker], threshold: float) -> dict[str, Any]:
    non_extra = [s for s in speakers if not s.is_extra]
    total_lines = sum(s.line_count or 0 for s in non_extra)

    def _covered(s: ProjectSpeaker) -> bool:
        # A manual decision (mapped or deliberately unmapped) counts as
        # reviewed; automatic mappings count only at/above the threshold.
        if s.match_origin == "manual":
            return True
        return s.character_id is not None and (s.match_confidence or 0.0) >= threshold

    covered_lines = sum(s.line_count or 0 for s in non_extra if _covered(s))
    unmapped = [
        s for s in non_extra
        if s.character_id is None and s.match_origin != "manual"
    ]
    below = sum(
        1 for s in non_extra
        if s.character_id is not None
        and s.match_origin != "manual"
        and (s.match_confidence or 0.0) < threshold
    )

    if not non_extra:
        coverage = None
        overall = "high"
    else:
        coverage = (covered_lines / total_lines) if total_lines else 1.0
        major_unmapped = any((s.line_count or 0) >= _MAJOR_SPEAKER_LINES for s in unmapped)
        if coverage >= 0.95 and not unmapped:
            overall = "high"
        elif coverage < 0.75 or major_unmapped:
            overall = "low"
        else:
            overall = "medium"

    return {
        "speakers_total": len(speakers),
        "non_extra": len(non_extra),
        "unmapped_non_extra": len(unmapped),
        "below_threshold": below,
        "threshold": threshold,
        "line_weighted_coverage": coverage,
        "overall": overall,
    }

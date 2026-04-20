from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.core.database import SyncSessionLocal
from app.db.models import QaItem, SubtitleChunk, SubtitleEvent
from app.grammar.providers import GrammarCheckResult, GrammarIssue, create_grammar_provider
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

# ISO 639-2 (3-char) to common provider language tags.
_LANG_MAP: dict[str, str] = {
    "pol": "pl-PL",
    "slk": "sk-SK", "slo": "sk-SK",
    "slv": "sl-SI",
    "hrv": "hr",
    "bul": "bg",
    "rus": "ru-RU",
    "ukr": "uk-UA",
    "srp": "sr",
    "deu": "de-DE", "ger": "de-DE",
    "fra": "fr-FR", "fre": "fr-FR",
    "spa": "es-ES", "esl": "es-ES",
    "ita": "it-IT",
    "jpn": "ja-JP",
    "eng": "en", "enm": "en",
    "nld": "nl-NL", "dut": "nl-NL",
    "por": "pt",
    "ron": "ro-RO", "rum": "ro-RO",
    "hun": "hu",
    "fin": "fi",
    "swe": "sv",
    "dan": "da",
    "nor": "no",
    "cat": "ca",
    "ell": "el", "gre": "el",
}

_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_ESCAPE_RE = re.compile(r"\\[Nnh]")


def _resolve_language(code: str | None) -> str:
    if not code:
        return "auto"
    normalized = code.strip().lower()
    return _LANG_MAP.get(normalized, normalized)


def _protect_ass(text: str) -> tuple[str, list[tuple[int, int]]]:
    buf = list(text)
    spans: list[tuple[int, int]] = []
    for pattern in (_ASS_TAG_RE, _ASS_ESCAPE_RE):
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
            for i in range(match.start(), match.end()):
                buf[i] = "\x00"
    return "".join(buf), spans


def _overlaps(offset: int, length: int, spans: list[tuple[int, int]]) -> bool:
    end = offset + length
    return any(start < end and stop > offset for start, stop in spans)


async def _check_text(provider: Any, text: str, language: str) -> GrammarCheckResult:
    return await provider.check(text, language)


def _run_check(provider: Any, text: str, language: str) -> GrammarCheckResult:
    return asyncio.run(_check_text(provider, text, language))


def _issue_details(
    issue: GrammarIssue,
    result: GrammarCheckResult,
    provider_name: str,
) -> dict[str, Any]:
    return {
        "provider": provider_name,
        "message": issue.message,
        "offset": issue.offset,
        "length": issue.length,
        "original": issue.original,
        "replacement": issue.replacement,
        "issue_type": issue.issue_type,
        "corrected_text": result.corrected_text,
    }


@register_job_handler("review_chunk_grammar")
def review_chunk_grammar(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    chunk_index: int = payload["chunk_index"]
    now = datetime.utcnow().isoformat()

    provider_name = ctx.options.grammar_provider
    base_url = (ctx.options.grammar_provider_base_url or "").strip()

    # "none" provider: skip grammar check entirely, immediately succeed.
    if provider_name == "none":
        now_str = datetime.utcnow().isoformat()
        with SyncSessionLocal() as session:
            chunk = session.scalar(
                select(SubtitleChunk)
                .where(SubtitleChunk.file_id == file_id)
                .where(SubtitleChunk.chunk_index == chunk_index)
            )
            if chunk is None:
                return JobResult(status="failed", result=None,
                                 error_code="CHUNK_NOT_FOUND",
                                 error_message=f"Chunk {chunk_index} for file {file_id} not found")
            chunk.status = "grammar_reviewed"
            chunk.updated_at = now_str
            session.commit()
        return JobResult(
            status="succeeded",
            result={"events_checked": 0, "warnings_created": 0},
            error_code=None,
            error_message=None,
        )

    if not base_url:
        return JobResult(
            status="failed",
            result=None,
            error_code="GRAMMAR_PROVIDER_NOT_CONFIGURED",
            error_message="GRAMMAR_PROVIDER_BASE_URL is not configured",
        )

    try:
        provider = create_grammar_provider(provider_name, base_url)
    except ValueError as exc:
        return JobResult(
            status="failed",
            result=None,
            error_code="GRAMMAR_PROVIDER_NOT_CONFIGURED",
            error_message=str(exc),
        )

    normalized_base_url = getattr(provider, "base_url", base_url)
    endpoint_url = getattr(provider, "endpoint_url", normalized_base_url)

    language = _resolve_language(ctx.options.target_lang_code)
    progress(0.05, "Loading chunk definition")

    with SyncSessionLocal() as session:
        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is None:
            return JobResult(status="failed", result=None,
                             error_code="CHUNK_NOT_FOUND",
                             error_message=f"Chunk {chunk_index} for file {file_id} not found")
        if chunk.status != "rules_reviewed":
            return JobResult(status="failed", result=None,
                             error_code="CHUNK_NOT_RULES_REVIEWED",
                             error_message=(
                                 f"Chunk {chunk_index} has status '{chunk.status}'; "
                                 "review_chunk_grammar requires status 'rules_reviewed'"
                             ))

        events: list[SubtitleEvent] = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.line_index >= chunk.translate_from_line)
            .where(SubtitleEvent.line_index <= chunk.translate_to_line)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

        snapshot = [
            {"id": event.id, "translated_text": event.translated_text or ""}
            for event in events
        ]

    if not snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events in target range for chunk {chunk_index}")

    logger.debug(
        "review_chunk_grammar provider=%s base_url=%s endpoint=%s file_id=%d chunk_index=%d events=%d",
        provider_name,
        normalized_base_url,
        endpoint_url,
        file_id,
        chunk_index,
        len(snapshot),
    )
    progress(0.15, f"Running grammar review with {provider_name} on {len(snapshot)} events")

    events_checked = 0
    warnings_created = 0
    collected_warnings: list[dict[str, Any]] = []

    for i, snap in enumerate(snapshot):
        text = snap["translated_text"]
        if not text.strip():
            events_checked += 1
            continue

        protected, spans = _protect_ass(text)
        try:
            result = _run_check(provider, protected, language)
        except (httpx.HTTPError, ValueError) as exc:
            message = (
                f"Grammar provider '{provider_name}' at '{normalized_base_url}' "
                f"failed while calling '{endpoint_url}': {exc}"
            )
            logger.warning("Grammar provider request failed for event %s: %s", snap["id"], message)
            return JobResult(
                status="failed",
                result=None,
                error_code="GRAMMAR_PROVIDER_ERROR",
                error_message=message,
            )

        for issue in result.matches:
            if _overlaps(issue.offset, issue.length, spans):
                continue
            collected_warnings.append(dict(
                file_id=file_id,
                subtitle_event_id=snap["id"],
                severity="warning",
                qa_type="grammar",
                message=issue.message,
                details_json=json.dumps(_issue_details(issue, result, provider_name)),
                is_resolved=0,
                created_at=now,
            ))
            warnings_created += 1

        events_checked += 1
        if i % 10 == 0:
            progress(0.15 + 0.65 * (i / len(snapshot)),
                     f"Processed {i + 1}/{len(snapshot)} events")

    progress(0.82, "Writing results")

    with SyncSessionLocal() as session:
        if collected_warnings:
            session.execute(QaItem.__table__.insert(), collected_warnings)

        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = "grammar_reviewed"
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={"events_checked": events_checked, "warnings_created": warnings_created},
        error_code=None,
        error_message=None,
    )


@register_job_handler("review_chunk_languagetool")
def review_chunk_languagetool_compat(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    return review_chunk_grammar(payload, ctx, progress)

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.database import SyncSessionLocal
from app.db.models import QaItem, SubtitleChunk, SubtitleEvent
from app.jobs.context import JobContext, JobResult, ProgressFn
from app.jobs.registry import register_job_handler

logger = logging.getLogger(__name__)

# qa_types produced by this reviewer — used to scope deletion of old results
_REVIEW_QA_TYPES = {
    "long_line",
    "high_cps",
    "repeated_punctuation",
    "repeated_words",
    "untranslated_english",
    "short_ambiguous_line",
    "literal_phrasing",
}

# Signal weights
_STRONG_WEIGHT = 3
_MINOR_WEIGHT = 1
_STRONG_TYPES = {"untranslated_english", "short_ambiguous_line", "literal_phrasing"}

# LLM review threshold
_SCORE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_ASS_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_ESCAPE_RE = re.compile(r"\\[Nnh]")


def _clean(text: str) -> str:
    """Strip ASS inline tags and escape sequences."""
    text = _ASS_TAG_RE.sub("", text)
    text = _ASS_ESCAPE_RE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Individual checks — return list of (qa_type, message, details, weight)
# ---------------------------------------------------------------------------

def _check_long_line(snap: dict) -> list[tuple[str, str, dict, int]]:
    src = _clean(snap["source_text"] or "")
    tgt = _clean(snap["translated_text"] or "")
    if not src:
        return []
    ratio = len(tgt) / len(src)
    if ratio > 1.5:
        return [("long_line",
                 f"Translation is {ratio:.1f}× longer than source.",
                 {"source_len": len(src), "translated_len": len(tgt), "ratio": round(ratio, 2)},
                 _MINOR_WEIGHT)]
    return []


def _check_high_cps(snap: dict) -> list[tuple[str, str, dict, int]]:
    duration_ms = snap["end_ms"] - snap["start_ms"]
    if duration_ms <= 0:
        return []
    tgt = _clean(snap["translated_text"] or "")
    cps = len(tgt) / (duration_ms / 1000.0)
    if cps > 25.0:
        return [("high_cps",
                 f"Character rate is {cps:.1f} CPS (threshold: 25).",
                 {"cps": round(cps, 1), "duration_ms": duration_ms, "threshold": 25},
                 _MINOR_WEIGHT)]
    return []


_REPEATED_PUNCT_RE = re.compile(r"[!?]{3,}|[,;]{2,}")


def _check_repeated_punctuation(snap: dict) -> list[tuple[str, str, dict, int]]:
    tgt = snap["translated_text"] or ""
    matches = _REPEATED_PUNCT_RE.findall(tgt)
    if matches:
        return [("repeated_punctuation",
                 "Unusual punctuation repetition detected.",
                 {"matches": matches[:5]},
                 _MINOR_WEIGHT)]
    return []


# Short stop words that can naturally repeat
_REPEAT_STOP = {"a", "i", "v", "z", "s", "k", "o", "se", "si", "to", "ne",
                "je", "jsou", "byl", "byla", "the", "a", "in", "is", "it"}


def _check_repeated_words(snap: dict) -> list[tuple[str, str, dict, int]]:
    tgt = _clean(snap["translated_text"] or "")
    words = re.findall(r"\b\w{3,}\b", tgt.lower(), re.UNICODE)
    counts = Counter(words)
    repeats = {w: c for w, c in counts.items() if c >= 3 and w not in _REPEAT_STOP}
    if repeats:
        return [("repeated_words",
                 "Same word repeated 3+ times in one line.",
                 {"words": repeats},
                 _MINOR_WEIGHT)]
    return []


# Common English function words that should not survive translation
_ENGLISH_MARKERS = {
    "the", "and", "but", "that", "with", "have", "this", "from", "they",
    "what", "when", "your", "would", "about", "there", "their", "which",
    "could", "should", "where", "while", "because", "although", "however",
    "therefore", "moreover", "furthermore", "anyway", "something", "nothing",
    "everything", "everyone", "someone", "anyone",
}


def _check_untranslated_english(snap: dict) -> list[tuple[str, str, dict, int]]:
    src = _clean(snap["source_text"] or "").lower()
    tgt = _clean(snap["translated_text"] or "").lower()

    src_words = set(re.findall(r"\b[a-z]{3,}\b", src))
    tgt_words = set(re.findall(r"\b[a-z]{3,}\b", tgt))

    english_in_tgt = tgt_words & _ENGLISH_MARKERS

    overlap_ratio = 0.0
    if src_words and tgt_words:
        overlap = src_words & tgt_words
        overlap_ratio = len(overlap) / max(len(src_words), len(tgt_words))

    issues: list[str] = []
    if len(english_in_tgt) >= 2:
        issues.append("english_markers")
    if overlap_ratio > 0.5 and len(src_words) >= 4:
        issues.append("high_source_overlap")

    if issues:
        return [("untranslated_english",
                 "Translation may still contain untranslated English words.",
                 {
                     "english_markers_found": sorted(english_in_tgt),
                     "source_target_overlap_ratio": round(overlap_ratio, 2),
                     "issues": issues,
                 },
                 _STRONG_WEIGHT)]
    return []


def _check_short_ambiguous(snap: dict) -> list[tuple[str, str, dict, int]]:
    tgt = _clean(snap["translated_text"] or "")
    without_space = re.sub(r"\s+", "", tgt)
    length = len(without_space)
    if 0 < length <= 3:
        return [("short_ambiguous_line",
                 f"Translation is very short ({length} chars) and may be ambiguous.",
                 {"translated_len": length},
                 _STRONG_WEIGHT)]
    return []


# English constructions that suggest the text was not translated
_LITERAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bi am\b", re.IGNORECASE), "literal_i_am"),
    (re.compile(r"\byou are\b", re.IGNORECASE), "literal_you_are"),
    (re.compile(r"\bhe is\b|\bshe is\b|\bit is\b", re.IGNORECASE), "literal_be_verb"),
    (re.compile(r"\bdo not\b|\bdoes not\b|\bdid not\b", re.IGNORECASE), "literal_negation"),
    (re.compile(r"\bwhat is\b|\bwhere is\b|\bwho is\b", re.IGNORECASE), "literal_question"),
    (re.compile(r"\bI don't\b|\bI can't\b|\bI won't\b", re.IGNORECASE), "literal_contraction"),
    (re.compile(r"\bthank you\b", re.IGNORECASE), "literal_phrase"),
    (re.compile(r"\bof course\b", re.IGNORECASE), "literal_phrase"),
    (re.compile(r"\bright now\b", re.IGNORECASE), "literal_phrase"),
]


def _check_literal_phrasing(snap: dict) -> list[tuple[str, str, dict, int]]:
    src = _clean(snap["source_text"] or "")
    tgt = _clean(snap["translated_text"] or "")

    matched: list[str] = []
    for pattern, name in _LITERAL_PATTERNS:
        if pattern.search(tgt):
            matched.append(name)

    # Bigram overlap — high similarity suggests word-for-word translation
    src_tokens = src.lower().split()
    tgt_tokens = tgt.lower().split()
    if len(src_tokens) >= 5 and len(tgt_tokens) >= 5:
        src_bigrams = set(zip(src_tokens, src_tokens[1:]))
        tgt_bigrams = set(zip(tgt_tokens, tgt_tokens[1:]))
        if src_bigrams and tgt_bigrams:
            overlap = len(src_bigrams & tgt_bigrams) / max(len(src_bigrams), len(tgt_bigrams))
            if overlap > 0.4:
                matched.append("high_bigram_overlap")

    if matched:
        return [("literal_phrasing",
                 "Translation may contain literal or word-for-word phrasing.",
                 {"patterns": matched},
                 _STRONG_WEIGHT)]
    return []


_CHECKS = [
    _check_long_line,
    _check_high_cps,
    _check_repeated_punctuation,
    _check_repeated_words,
    _check_untranslated_english,
    _check_short_ambiguous,
    _check_literal_phrasing,
]


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register_job_handler("review_chunk_rules")
def review_chunk_rules(
    payload: dict[str, Any],
    ctx: JobContext,
    progress: ProgressFn,
) -> JobResult:
    file_id: int = payload["file_id"]
    chunk_index: int = payload["chunk_index"]
    now = datetime.utcnow().isoformat()

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
        if chunk.status != "validated":
            return JobResult(status="failed", result=None,
                             error_code="CHUNK_NOT_VALIDATED",
                             error_message=(
                                 f"Chunk {chunk_index} has status '{chunk.status}'; "
                                 "review_chunk_rules requires status 'validated'"
                             ))

        translate_from = chunk.translate_from_line
        translate_to = chunk.translate_to_line

        target_events: list[SubtitleEvent] = list(session.scalars(
            select(SubtitleEvent)
            .where(SubtitleEvent.file_id == file_id)
            .where(SubtitleEvent.line_index >= translate_from)
            .where(SubtitleEvent.line_index <= translate_to)
            .where(SubtitleEvent.event_type == "dialogue")
            .order_by(SubtitleEvent.line_index)
        ).all())

        events_snapshot = [
            {
                "id": e.id,
                "line_index": e.line_index,
                "source_text": e.source_text,
                "translated_text": e.translated_text,
                "start_ms": e.start_ms,
                "end_ms": e.end_ms,
            }
            for e in target_events
        ]

    if not events_snapshot:
        return JobResult(status="failed", result=None,
                         error_code="NO_TARGET_EVENTS",
                         error_message=f"No dialogue events in target range for chunk {chunk_index}")

    progress(0.2, f"Reviewing {len(events_snapshot)} events")

    # Run checks in-memory
    collected_warnings: list[dict] = []
    chunk_score = 0
    llm_review_needed = False

    for snap in events_snapshot:
        for check_fn in _CHECKS:
            results = check_fn(snap)
            for qa_type, message, details, weight in results:
                chunk_score += weight
                if qa_type in _STRONG_TYPES:
                    llm_review_needed = True
                collected_warnings.append(dict(
                    file_id=file_id,
                    subtitle_event_id=snap["id"],
                    severity="warning",
                    qa_type=qa_type,
                    message=message,
                    details_json=json.dumps(details) if details else None,
                    is_resolved=0,
                    created_at=now,
                ))

    if chunk_score >= _SCORE_THRESHOLD:
        llm_review_needed = True

    progress(0.7, f"Writing {len(collected_warnings)} warnings")

    with SyncSessionLocal() as session:
        if collected_warnings:
            session.execute(QaItem.__table__.insert(), collected_warnings)

        chunk = session.scalar(
            select(SubtitleChunk)
            .where(SubtitleChunk.file_id == file_id)
            .where(SubtitleChunk.chunk_index == chunk_index)
        )
        if chunk is not None:
            chunk.status = "rules_reviewed"
            chunk.llm_review_needed = 1 if llm_review_needed else 0
            chunk.updated_at = now

        session.commit()

    progress(1.0, "Done")
    return JobResult(
        status="succeeded",
        result={
            "warnings_created": len(collected_warnings),
            "llm_review_needed": llm_review_needed,
        },
        error_code=None,
        error_message=None,
    )

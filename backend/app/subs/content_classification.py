"""Heuristic content-type classification for subtitle events.

Tag-based signals are checked before style-name signals because many
fansub scripts leave styles unnamed/generic ("Default") or reuse one style
for both dialogue and signs — tag presence is unambiguous ASS semantics,
style naming is not. Classification never excludes a line from
translation; it only changes which prompt/validation path is used.

Used by extract_subtitles (initial per-event classification) and by
plan_translation_chunks (re-classification when a speaker content tag is
removed).
"""
from __future__ import annotations

import re

_KARAOKE_TAG_RE = re.compile(r"\\k[fo]?\d", re.IGNORECASE)
_POSITIONING_TAG_RE = re.compile(r"\\(?:pos|move|org|clip|iclip|t\()", re.IGNORECASE)
# Word-boundary search: real releases compose lyric style names ("Romaji
# Main", "ED Eng Main", "Copy of ED Romanji Secondary"). A bare "English"
# style is deliberately NOT matched — some releases use it for dialogue.
_SONG_STYLE_RE = re.compile(
    r"\b(op|ed|oped|song|insert|kara|karaoke|romaji|romanji|lyrics?)\d*\b",
    re.IGNORECASE,
)
_SIGN_STYLE_RE = re.compile(r"sign|title|caption|note|typeset|credit|logo", re.IGNORECASE)
_TAG_BLOCK_RE = re.compile(r"\{[^}]*\}")


def classify_content_type(event_type: str, style: str, text: str) -> tuple[str, str | None]:
    if event_type == "comment":
        return "other", "ass_comment"

    if _KARAOKE_TAG_RE.search(text):
        return "karaoke", "k_tag"

    if _POSITIONING_TAG_RE.search(text):
        return "sign", "positioning_tag"

    if style and _SONG_STYLE_RE.search(style):
        return "song", "style_name"

    if style and _SIGN_STYLE_RE.search(style):
        return "sign", "style_name"

    tag_chars = sum(len(m) for m in _TAG_BLOCK_RE.findall(text))
    if len(text) > 0 and (tag_chars / len(text)) > 0.3:
        return "sign", "tag_density"

    return "dialogue", None

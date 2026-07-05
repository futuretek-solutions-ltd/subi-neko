"""Episode-number extraction from anime release filenames.

Deliberately conservative: a wrong episode number injects the wrong episode
title/synopsis into prompts, so when in doubt return None. Import/title
matching stays manual — this only links files to already-fetched episode
metadata.
"""
from __future__ import annotations

import re

# Noise stripped before parsing: bracketed release groups/CRC/tags,
# resolution/codec tokens, and the file extension.
_BRACKETED_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")
_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{2,4}$")
_NOISE_TOKEN_RE = re.compile(
    r"\b(\d{3,4}p|\d{3,4}x\d{3,4}|x26[45]|h\.?26[45]|hevc|avc|aac|ac3|flac|opus|"
    r"bd(rip)?|bluray|blu-ray|web(-?dl|rip)?|hdtv|dvd(rip)?|remux|10bit|8bit|hi10p?|"
    r"dual[- ]?audio|multi[- ]?sub|uncensored|v\d)\b",
    re.IGNORECASE,
)

# Ordered by confidence — first hit wins.
_PATTERNS: list[re.Pattern] = [
    # S01E12, s1e3
    re.compile(r"\bS\d{1,2}[\s._-]*E(\d{1,4})\b", re.IGNORECASE),
    # E12 / EP12 / Ep. 12 / Episode 12 / #12
    re.compile(r"\b(?:E|EP)\.?\s*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\bEpisode\s*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"#(\d{1,4})\b"),
    # "Title - 12" / "Title - 12 END" / "Title - 12.5" (fractional → reject)
    re.compile(r"[\s._]-[\s._]*(\d{1,4})(?:\.(\d))?(?=[\s._]|$)"),
]

# A bare trailing number ("Title 12") — only trusted when it isn't a year.
_TRAILING_RE = re.compile(r"[\s._](\d{1,3})$")

_YEAR_RANGE = range(1900, 2100)


def parse_episode_number(filename: str) -> int | None:
    name = _EXTENSION_RE.sub("", filename)
    name = _BRACKETED_RE.sub(" ", name)
    name = _NOISE_TOKEN_RE.sub(" ", name)
    name = re.sub(r"(?<=\d)v\d+\b", "", name)  # release version suffix: "03v2" → "03"
    name = re.sub(r"\s+", " ", name.replace("_", " ")).strip()

    for pattern in _PATTERNS:
        match = pattern.search(name)
        if match is None:
            continue
        if len(match.groups()) > 1 and match.group(2) is not None:
            return None  # fractional episode ("12.5" recap) — don't guess
        number = int(match.group(1))
        if number in _YEAR_RANGE and pattern is _PATTERNS[-1]:
            continue  # "Title - 2021" is a year, not an episode
        if 0 < number < 1900:
            return number

    match = _TRAILING_RE.search(name)
    if match is not None:
        number = int(match.group(1))
        if 0 < number < 1900 and number not in _YEAR_RANGE:
            return number

    return None

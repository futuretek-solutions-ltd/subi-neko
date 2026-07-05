"""Deterministic row rebalancing for over-long dialogue rows.

Runs in review_chunk_final (before the readability check) when
AUTO_LINE_BREAK is on: a dialogue line whose row(s) exceed the row-length
limit is re-broken at a word boundary into two balanced rows. The long_row
check then only flags lines that even a balanced split cannot fit — real
condensing work for the reviewer instead of mechanical rewrapping.

Deliberately conservative: lines with inline override tags, soft breaks
(\\n) or hard spaces (\\h) are left untouched, because break placement may
interact with positioning/typesetting.
"""
from __future__ import annotations

import re

_LEADING_OVERRIDE_RE = re.compile(r"^(?:\{[^}]*\})+")
_HARD_BREAK_RE = re.compile(r"\s*\\N\s*")


def rebalance_rows(text: str, max_row_chars: int) -> str | None:
    """Return `text` re-broken so no row exceeds `max_row_chars`, or None
    when the line already fits, can't be fixed with two rows, or isn't safe
    to touch."""
    if not text:
        return None

    prefix, body = "", text
    m = _LEADING_OVERRIDE_RE.match(text)
    if m:
        prefix, body = text[: m.end()], text[m.end():]

    if "{" in body or "\\n" in body or "\\h" in body:
        return None

    rows = _HARD_BREAK_RE.split(body.strip())
    if all(len(row) <= max_row_chars for row in rows):
        return None

    words = " ".join(rows).split()
    if not words:
        return None

    full = " ".join(words)
    if len(full) <= max_row_chars:
        fixed = prefix + full
        return fixed if fixed != text else None

    best: tuple[int, str, str] | None = None
    for i in range(1, len(words)):
        row1 = " ".join(words[:i])
        row2 = " ".join(words[i:])
        if len(row1) <= max_row_chars and len(row2) <= max_row_chars:
            diff = abs(len(row1) - len(row2))
            if best is None or diff < best[0]:
                best = (diff, row1, row2)

    if best is None:
        return None  # no two-row split fits — surfaces as long_row

    fixed = f"{prefix}{best[1]}\\N{best[2]}"
    return fixed if fixed != text else None

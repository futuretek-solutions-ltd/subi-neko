"""Deterministic Czech-quality and readability flaggers.

These run in review_chunk_final after the polish pass. They are *flaggers*,
never auto-fixers: a hit either routes the line into the targeted polish
re-pass (first time) or surfaces as a warning QaItem for the reviewer.

Czech grammar tooling is not available, so these checks are deliberately
narrow, high-precision patterns rather than a grammar model.
"""
from __future__ import annotations

import re

from app.subs.tag_masking import plain_text

# Findings: (qa_type, message, details)
Finding = tuple[str, str, dict]

# ---------------------------------------------------------------------------
# Gender agreement — first-person past tense / conditional
#
# Czech past-tense participles agree with the speaker:
#   male:   "šel jsem", "byl bych", "viděl jsem"
#   female: "šla jsem", "byla bych", "viděla jsem"
# We check the participle adjacent to 1st-person auxiliaries (jsem/bych),
# in both orders ("viděl jsem" and "jsem viděl").
# ---------------------------------------------------------------------------

_PARTICIPLE_BEFORE_AUX = re.compile(
    r"\b([\w]{2,}?)(la|lo|li|ly|l)\s+(?:jsem|bych)\b", re.IGNORECASE | re.UNICODE)
_PARTICIPLE_AFTER_AUX = re.compile(
    r"\b(?:jsem|bych)\s+(?:se\s+|si\s+)?([\w]{2,}?)(la|lo|li|ly|l)\b", re.IGNORECASE | re.UNICODE)


def check_gender_agreement(translated: str, speaker_gender: str | None) -> list[Finding]:
    if speaker_gender not in ("male", "female"):
        return []
    text = plain_text(translated)

    candidates: list[tuple[str, str]] = []  # (word, ending)
    for pattern in (_PARTICIPLE_BEFORE_AUX, _PARTICIPLE_AFTER_AUX):
        for match in pattern.finditer(text):
            candidates.append((match.group(1) + match.group(2), match.group(2).lower()))

    if not candidates:
        return []

    expected = "l" if speaker_gender == "male" else "la"
    wrong = "la" if speaker_gender == "male" else "l"

    # A noun ending in -l/-la can sit next to "jsem" ("stůl jsem koupila"),
    # so only flag when NO correctly-gendered participle candidate exists —
    # precision over recall.
    has_correct = any(ending == expected for _, ending in candidates)
    mismatched = [word for word, ending in candidates if ending == wrong]

    if mismatched and not has_correct:
        return [(
            "gender_agreement",
            f"Past-tense form does not match speaker gender ({speaker_gender}).",
            {"speaker_gender": speaker_gender, "words": mismatched[:5]},
        )]
    return []


# ---------------------------------------------------------------------------
# T–V mixing inside a single line ("můžeš mi říct, co vás sem přivádí?")
# Cross-line consistency needs addressee tracking (phase 2); a single line
# that mixes tykání and vykání towards the same addressee is almost always
# a translation error, so only that narrow case is flagged.
# ---------------------------------------------------------------------------

_T_MARKERS = re.compile(r"\b(ty|tě|ti|tebe|tobě|tvůj|tvoje|tvá|tvé|tvého|tvou)\b", re.IGNORECASE)
_V_MARKERS = re.compile(r"\b(vás|vám|vámi|váš|vaše|vašeho|vaší|vaši)\b", re.IGNORECASE)


def check_tv_mixed_in_line(translated: str) -> list[Finding]:
    text = plain_text(translated)
    t_hits = _T_MARKERS.findall(text)
    v_hits = _V_MARKERS.findall(text)
    if t_hits and v_hits:
        return [(
            "tv_address_mixed",
            "Line mixes informal (tykání) and formal (vykání) address.",
            {"informal": t_hits[:3], "formal": v_hits[:3]},
        )]
    return []


def check_tv_against_pairs(translated: str, speaker_pair_modes: set[str]) -> list[Finding]:
    """Compare a line's T/V markers against the speaker's stored address
    pairs. Only fires when the speaker addresses EVERYONE the same way
    (uniform mode) — a speaker with mixed relationships can't be checked
    without per-line addressee attribution."""
    if speaker_pair_modes not in ({"tykani"}, {"vykani"}):
        return []
    expected = next(iter(speaker_pair_modes))

    text = plain_text(translated)
    t_hits = _T_MARKERS.findall(text)
    v_hits = _V_MARKERS.findall(text)

    if expected == "tykani" and v_hits and not t_hits:
        return [(
            "tv_address_mismatch",
            "Formal address (vykání) used by a speaker who addresses everyone informally.",
            {"expected": expected, "found": v_hits[:3]},
        )]
    if expected == "vykani" and t_hits and not v_hits:
        return [(
            "tv_address_mismatch",
            "Informal address (tykání) used by a speaker who addresses everyone formally.",
            {"expected": expected, "found": t_hits[:3]},
        )]
    return []


# ---------------------------------------------------------------------------
# Vocative — names in direct-address position must use the glossary's
# vocative form ("Ahoj, Tomáši!" not "Ahoj, Tomáš!")
# ---------------------------------------------------------------------------

def check_vocative(translated: str, vocatives: dict[str, str]) -> list[Finding]:
    """vocatives: nominative name → vocative form (from the glossary).
    Flags the nominative appearing in a direct-address position."""
    text = plain_text(translated)
    findings: list[Finding] = []
    for name, vocative in vocatives.items():
        if not name or not vocative or name == vocative:
            continue
        # Direct-address positions: line-initial "Name, …"/"Name!" or
        # after a comma "…, Name." / "…, Name," / "…, Name!"
        pattern = re.compile(
            rf"(?:^|,\s+){re.escape(name)}(?:\s*[,.!?…]|$)"
        )
        if pattern.search(text):
            findings.append((
                "vocative_missing",
                f'"{name}" appears in direct address — expected vocative "{vocative}".',
                {"name": name, "vocative": vocative},
            ))
    return findings


# ---------------------------------------------------------------------------
# Readability — CPS, row length, row count
# ---------------------------------------------------------------------------

def check_readability(
    translated: str,
    duration_ms: int,
    cps_limit: float,
    max_row_chars: int,
) -> list[Finding]:
    findings: list[Finding] = []
    rows = [plain_text(part) for part in re.split(r"\\N", translated or "")]
    visible = " ".join(row for row in rows if row)

    if duration_ms > 0 and visible:
        cps = len(visible) / (duration_ms / 1000.0)
        if cps > cps_limit:
            budget = int(cps_limit * duration_ms / 1000.0)
            findings.append((
                "high_cps",
                f"Reading speed {cps:.1f} CPS exceeds limit {cps_limit:.0f} "
                f"(fits in ~{budget} chars).",
                {"cps": round(cps, 1), "limit": cps_limit, "char_budget": budget},
            ))

    long_rows = [row for row in rows if len(row) > max_row_chars]
    if long_rows:
        findings.append((
            "long_row",
            f"Row exceeds {max_row_chars} characters.",
            {"row_lengths": [len(r) for r in rows], "limit": max_row_chars},
        ))

    if len([row for row in rows if row]) > 2:
        findings.append((
            "too_many_rows",
            "Subtitle wraps to more than 2 rows.",
            {"rows": len(rows)},
        ))

    return findings


# ---------------------------------------------------------------------------
# Untranslated English (ported from the retired rules review)
# ---------------------------------------------------------------------------

_ENGLISH_MARKERS = {
    "the", "and", "but", "that", "with", "have", "this", "from", "they",
    "what", "when", "your", "would", "about", "there", "their", "which",
    "could", "should", "where", "while", "because", "although", "however",
    "therefore", "moreover", "furthermore", "anyway", "something", "nothing",
    "everything", "everyone", "someone", "anyone",
}


# Unicode-aware word tokens; \d and _ excluded. Czech diacritic words count
# as translated-language evidence in the ratio denominator.
_WORD_RE = re.compile(r"\b[^\W\d_]{3,}\b", re.UNICODE)

# Name-honorific compounds ("Ako-neechan", "Kiryuu-sensei") are preserved
# verbatim by design and must not count as untranslated-English evidence.
_HYPHEN_COMPOUND_RE = re.compile(r"\b\w+(?:-\w+)+\b", re.UNICODE)


def check_untranslated_english(
    source: str,
    translated: str,
    exclude_terms: set[str] | None = None,
) -> list[Finding]:
    src_clean = _HYPHEN_COMPOUND_RE.sub(" ", plain_text(source))
    tgt_clean = _HYPHEN_COMPOUND_RE.sub(" ", plain_text(translated))

    src_tokens = _WORD_RE.findall(src_clean)
    tgt_tokens = _WORD_RE.findall(tgt_clean)

    exclude = {t.lower() for t in (exclude_terms or set())}
    # Proper names survive translation on purpose: a token capitalized in
    # both source and target is a name, not untranslated English.
    exclude |= (
        {t.lower() for t in src_tokens if t[0].isupper()}
        & {t.lower() for t in tgt_tokens if t[0].isupper()}
    )

    src_words = {t.lower() for t in src_tokens if t.lower() not in exclude}
    tgt_words = {t.lower() for t in tgt_tokens if t.lower() not in exclude}
    # Only ASCII target tokens can be untranslated English; Czech words in
    # tgt_words still dilute the overlap ratio via the denominator.
    ascii_tgt = {w for w in tgt_words if w.isascii()}

    english_in_tgt = ascii_tgt & _ENGLISH_MARKERS

    overlap_ratio = 0.0
    if src_words and tgt_words:
        overlap = src_words & ascii_tgt
        overlap_ratio = len(overlap) / max(len(src_words), len(tgt_words))

    issues: list[str] = []
    if len(english_in_tgt) >= 2:
        issues.append("english_markers")
    if overlap_ratio > 0.5 and len(src_words) >= 4:
        issues.append("high_source_overlap")

    if issues:
        return [(
            "untranslated_english",
            "Translation may still contain untranslated English.",
            {
                "english_markers_found": sorted(english_in_tgt),
                "source_target_overlap_ratio": round(overlap_ratio, 2),
                "issues": issues,
            },
        )]
    return []

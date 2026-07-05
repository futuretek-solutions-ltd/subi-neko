from __future__ import annotations

from types import SimpleNamespace

from app.jobs.handlers.prompt_context import (
    AnalysisContext,
    StyleContext,
    build_glossary_block,
    build_scene_block,
    build_style_block,
    build_tricky_notes_block,
)


def _term(source, target, category="other", vocative=None, gender=None, note=None):
    return SimpleNamespace(source_term=source, target_term=target, category=category,
                           vocative=vocative, gender=gender, note=note)


# ---------------------------------------------------------------------------
# Glossary block
# ---------------------------------------------------------------------------

def test_glossary_names_always_included():
    terms = [_term("Aria", "Aria", category="name", vocative="Ario", gender="female")]
    block = build_glossary_block(terms, ["Nothing relevant here."])
    assert '"Aria"' in block
    assert "vocative: Ario" in block
    assert "keep as-is" in block


def test_glossary_other_categories_filtered_by_chunk_text():
    terms = [
        _term("Dragon Slash", "Dračí sek", category="technique"),
        _term("Moon Blade", "Měsíční čepel", category="technique"),
    ]
    block = build_glossary_block(terms, ["He used Dragon Slash again!"])
    assert "Dračí sek" in block
    assert "Měsíční čepel" not in block


def test_glossary_matches_through_ass_markup():
    terms = [_term("Dragon Slash", "Dračí sek", category="technique")]
    block = build_glossary_block(terms, [r"He used {\i1}Dragon Slash{\i0}!"])
    assert "Dračí sek" in block


# ---------------------------------------------------------------------------
# Style block
# ---------------------------------------------------------------------------

def test_style_block_filters_voices_and_pairs_to_present_speakers():
    style = StyleContext(
        tone_summary="Dark fantasy.",
        voices={"Aria": ("blunt", "informal"), "Bob": ("flowery", "formal")},
        pairs=[("aria", "bob", "vykani"), ("carl", "bob", "tykani")],
    )
    identities = {"aria": ("Aria", "female"), "carl": ("Carl", "male")}

    block = build_style_block(style, {"aria"}, identities)

    assert "Dark fantasy." in block
    assert "Aria: blunt" in block
    assert "Bob: flowery" not in block            # Bob doesn't speak in this chunk
    assert "aria addresses bob: vykani" in block
    assert "carl addresses bob" not in block


# ---------------------------------------------------------------------------
# Scene / tricky notes
# ---------------------------------------------------------------------------

def test_scene_block_selects_overlapping_scenes():
    analysis = AnalysisContext(
        synopsis="Episode about a heist.",
        scenes=[
            {"from_line": 0, "to_line": 50, "summary": "Planning", "setting": "hideout"},
            {"from_line": 51, "to_line": 100, "summary": "The heist", "setting": "bank"},
        ],
    )
    block = build_scene_block(analysis, 60, 90)
    assert "Episode about a heist." in block
    assert "The heist" in block
    assert "Planning" not in block


def test_tricky_notes_only_for_given_lines():
    analysis = AnalysisContext(tricky_lines={5: "pun on 'bat'", 99: "sarcasm"})
    block = build_tricky_notes_block(analysis, [5, 6, 7])
    assert "pun on 'bat'" in block
    assert "sarcasm" not in block

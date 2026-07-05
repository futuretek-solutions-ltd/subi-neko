"""Unit tests for the sign-handling fixes: fragment detection, CPS char
budget floor, and cryptic speaker-label guards."""
from __future__ import annotations

from app.jobs.handlers.infer_character_mapping import is_cryptic_label
from app.jobs.handlers.polish_chunk import _char_budget
from app.jobs.handlers.translate_chunk import _detect_sign_fragments


def _sign(id_, line, text, start, end):
    return {
        "id": id_,
        "line_index": line,
        "source_text": text,
        "start_ms": start,
        "end_ms": end,
    }


# --- fragment detection ------------------------------------------------------

def test_fragment_pair_detected():
    # "For" + "bidden" at identical timestamps form one on-screen word.
    events = [
        _sign(1, 10, "{\\pos(298,19)}For", 1000, 2200),
        _sign(2, 11, "{\\pos(298,52)}bidden", 1000, 2200),
    ]
    lines, anchors = _detect_sign_fragments(events)
    assert lines == {10, 11}
    assert anchors == {"Forbidden": 1}


def test_fragment_repeated_frames_anchor_once():
    events = []
    for frame in range(3):
        t = 1000 + frame * 40
        events.append(_sign(frame * 2 + 1, frame * 2 + 10, "{\\pos(1,1)}For", t, t + 40))
        events.append(_sign(frame * 2 + 2, frame * 2 + 11, "{\\pos(2,2)}bidden", t, t + 40))
    lines, anchors = _detect_sign_fragments(events)
    assert len(lines) == 6
    assert list(anchors) == ["Forbidden"]  # one QA anchor per word


def test_two_capitalized_signs_not_fragments():
    # Two independent signs on screen at once ("Ume" + "Baths") both start
    # uppercase — not a mid-word split.
    events = [
        _sign(1, 10, "{\\pos(1,1)}Ume", 1000, 2000),
        _sign(2, 11, "{\\pos(2,2)}Baths", 1000, 2000),
    ]
    lines, anchors = _detect_sign_fragments(events)
    assert lines == set()
    assert anchors == {}


def test_multiword_signs_not_fragments():
    events = [
        _sign(1, 10, "{\\pos(1,1)}Ume Baths", 1000, 2000),
        _sign(2, 11, "{\\pos(2,2)}since 1969", 1000, 2000),
    ]
    lines, _ = _detect_sign_fragments(events)
    assert lines == set()


def test_lone_sign_not_fragment():
    lines, _ = _detect_sign_fragments([_sign(1, 10, "{\\pos(1,1)}Ume", 1000, 1040)])
    assert lines == set()


# --- polish char budget ------------------------------------------------------

def test_char_budget_normal_dialogue():
    # 3 s at 20 CPS → 60 chars.
    assert _char_budget(0, 3000, 20.0) == 60


def test_char_budget_floors_to_none_for_short_events():
    # 40 ms sign frame at 20 CPS must not become "max 0 chars".
    assert _char_budget(0, 40, 20.0) is None
    assert _char_budget(0, 50, 20.0) is None
    assert _char_budget(0, 450, 20.0) is None  # 9 chars — below the floor


def test_char_budget_zero_duration():
    assert _char_budget(1000, 1000, 20.0) is None
    assert _char_budget(1000, 900, 20.0) is None


# --- cryptic speaker labels --------------------------------------------------

def test_cryptic_labels():
    assert is_cryptic_label("20")
    assert is_cryptic_label("2")
    assert is_cryptic_label("ca")
    assert is_cryptic_label("")


def test_real_names_not_cryptic():
    assert not is_cryptic_label("ako")
    assert not is_cryptic_label("Suminoe Keita")
    assert not is_cryptic_label("txt")  # 3+ chars: plausible abbreviation, LLM decides

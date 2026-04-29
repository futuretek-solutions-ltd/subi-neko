from __future__ import annotations

from dataclasses import dataclass

from app.jobs.handlers.validate_chunk import (
    _check_escape_mismatch,
    _check_formatting_tag_mismatch,
    _check_text_corruption,
)


@dataclass
class EventProxy:
    translated_text: str
    source_text: str = ""


def test_text_corruption_ignores_valid_leading_ass_tags():
    issues = _check_text_corruption(
        EventProxy(r"{\pos(576,223.2)}{\an7}EPISODA 6")  # type: ignore[arg-type]
    )

    assert issues == []


def test_text_corruption_still_catches_json_like_output():
    issues = _check_text_corruption(EventProxy('{"translation": "EPISODA 6"}'))  # type: ignore[arg-type]

    assert issues
    assert issues[0][0] == "text_corruption"
    assert "json_like_output" in issues[0][2]["reasons"]


def test_text_corruption_allows_ass_newline_and_numbered_episode_title():
    issues = _check_text_corruption(
        EventProxy(r"{\an8}11. epizoda\NNouzový quest: Zachraňte Enyu!")  # type: ignore[arg-type]
    )

    assert issues == []


def test_text_corruption_allows_numbered_sentence_without_ass_tag():
    issues = _check_text_corruption(
        EventProxy('11. epizoda: "Nouzový quest: Zachraňte Enyu!"')  # type: ignore[arg-type]
    )

    assert issues == []


def test_escape_mismatch_accepts_preserved_ass_newline():
    issues = _check_escape_mismatch(
        EventProxy(
            translated_text=r"{\an8}11. epizoda\NNouzový quest: Zachraňte Enyu!",
            source_text=r"{\an8}Episode 11\NEmergency Quest: Save Enya!",
        )  # type: ignore[arg-type]
    )

    assert issues == []


def test_text_corruption_allows_bracketed_ass_screen_text_after_tags():
    issues = _check_text_corruption(
        EventProxy(
            translated_text=(
                r"{\fscx102\fscy118\frz9.139\pos(312.737,190.153)}"
                r"[Evergelion]\NPodrobnosti o produktu"
            ),
        )  # type: ignore[arg-type]
    )

    assert issues == []


def test_text_corruption_allows_bracketed_choice_text_after_tags():
    issues = _check_text_corruption(
        EventProxy(r"{\an1\fs16\shad0\bord0\pos(22,210)}[A/N]")  # type: ignore[arg-type]
    )

    assert issues == []


def test_formatting_check_allows_preserved_double_brace_ass_override():
    source = r"{{\shad0Z\fs15\3c&HC8A07F&\move(350.743,94.914,353.743,88.914,24,3111)}Item/Skin"
    translated = r"{{\shad0Z\fs15\3c&HC8A07F&\move(350.743,94.914,353.743,88.914,24,3111)}Předmět/Vzhled"

    issues = _check_formatting_tag_mismatch(
        EventProxy(translated_text=translated, source_text=source)  # type: ignore[arg-type]
    )

    assert issues == []


def test_text_corruption_allows_double_brace_ass_override():
    issues = _check_text_corruption(
        EventProxy(
            r"{{\shad0Z\fs15\3c&HC8A07F&\move(350.743,94.914,353.743,88.914,24,3111)}Předmět/Vzhled"
        )  # type: ignore[arg-type]
    )

    assert issues == []


def test_formatting_check_still_rejects_missing_ass_override():
    issues = _check_formatting_tag_mismatch(
        EventProxy(
            translated_text="Bez tagu",
            source_text=r"{\an8}With tag",
        )  # type: ignore[arg-type]
    )

    assert issues
    assert issues[0][0] == "formatting_tag_mismatch"

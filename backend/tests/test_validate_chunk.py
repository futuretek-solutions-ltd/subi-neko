from __future__ import annotations

from dataclasses import dataclass

from app.jobs.handlers.validate_chunk import _check_text_corruption


@dataclass
class EventProxy:
    translated_text: str


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

from __future__ import annotations

import httpx
import pytest

from app.grammar.providers import KorektorProvider, LanguageToolProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected_path"),
    [
        ("http://lt:8010", "/v2/check"),
        ("http://lt:8010/v2", "/v2/check"),
    ],
)
async def test_languagetool_url_building(base_url: str, expected_path: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        assert request.url.path == expected_path
        assert b"language=en" in body
        assert b"text=This+are+wrong" in body
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "message": "Possible agreement issue",
                        "offset": 5,
                        "length": 3,
                        "replacements": [{"value": "is"}],
                        "rule": {"issueType": "grammar"},
                        "type": {"typeName": "Other"},
                    }
                ]
            },
        )

    provider = LanguageToolProvider(base_url, transport=httpx.MockTransport(handler))

    result = await provider.check("This are wrong", "en")

    assert result.text == "This are wrong"
    assert result.corrected_text is None
    assert len(result.matches) == 1
    issue = result.matches[0]
    assert issue.message == "Possible agreement issue"
    assert issue.offset == 5
    assert issue.length == 3
    assert issue.original == "are"
    assert issue.replacement == "is"
    assert issue.issue_type == "grammar"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected_path"),
    [
        ("http://korektor:8010", "/check"),
        ("http://korektor:8010/", "/check"),
        ("http://korektor:8010/check", "/check"),
    ],
)
async def test_korektor_url_building(base_url: str, expected_path: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_path
        assert await request.aread() == b'{"text":"Toto jsu test"}'
        return httpx.Response(
            200,
            json={
                "text": "Toto jsu test",
                "corrected_text": "Toto je test",
                "matches": [
                    {
                        "message": "Typo",
                        "offset": 5,
                        "length": 3,
                        "original": "jsu",
                        "replacement": "je",
                        "issue_type": "spelling",
                    }
                ],
            },
        )

    provider = KorektorProvider(base_url, transport=httpx.MockTransport(handler))

    result = await provider.check("Toto jsu test", "cs")

    assert result.text == "Toto jsu test"
    assert result.corrected_text == "Toto je test"
    assert len(result.matches) == 1
    issue = result.matches[0]
    assert issue.message == "Typo"
    assert issue.offset == 5
    assert issue.length == 3
    assert issue.original == "jsu"
    assert issue.replacement == "je"
    assert issue.issue_type == "spelling"

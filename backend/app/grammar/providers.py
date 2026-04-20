from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GrammarIssue:
    message: str
    offset: int
    length: int
    original: str
    replacement: str | None
    issue_type: str


@dataclass(frozen=True)
class GrammarCheckResult:
    text: str
    corrected_text: str | None
    matches: list[GrammarIssue]


class GrammarProvider(Protocol):
    async def check(self, text: str, language: str) -> GrammarCheckResult:
        ...


class LanguageToolProvider:
    def __init__(self, base_url: str, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    @property
    def endpoint_url(self) -> str:
        base = self.base_url
        if base.endswith("/v2/check"):
            return base
        if base.endswith("/v2"):
            return f"{base}/check"
        return f"{base}/v2/check"

    async def check(self, text: str, language: str) -> GrammarCheckResult:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(
                self.endpoint_url,
                data={"language": language, "text": text},
            )
            response.raise_for_status()
        data = response.json()
        return GrammarCheckResult(
            text=text,
            corrected_text=None,
            matches=[self._map_match(text, match) for match in data.get("matches", [])],
        )

    @staticmethod
    def _map_match(text: str, match: dict[str, Any]) -> GrammarIssue:
        offset = int(match.get("offset", 0))
        length = int(match.get("length", 0))
        replacements = match.get("replacements") or []
        replacement = None
        if replacements:
            first = replacements[0]
            if isinstance(first, dict):
                replacement = first.get("value")
        rule = match.get("rule") or {}
        rule_type = rule.get("issueType")
        fallback_type = ((match.get("type") or {}).get("typeName"))
        return GrammarIssue(
            message=match.get("message") or "Grammar suggestion",
            offset=offset,
            length=length,
            original=text[offset:offset + length],
            replacement=replacement,
            issue_type=rule_type or fallback_type or "grammar",
        )


class KorektorProvider:
    def __init__(self, base_url: str, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    @property
    def endpoint_url(self) -> str:
        if self.base_url.endswith("/check"):
            return self.base_url
        return f"{self.base_url}/check"

    async def check(self, text: str, language: str) -> GrammarCheckResult:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(
                self.endpoint_url,
                json={"text": text},
            )
            response.raise_for_status()
        data = response.json()
        return GrammarCheckResult(
            text=data.get("text", text),
            corrected_text=data.get("corrected_text"),
            matches=[self._map_issue(item) for item in data.get("matches", [])],
        )

    @staticmethod
    def _map_issue(item: dict[str, Any]) -> GrammarIssue:
        return GrammarIssue(
            message=item.get("message") or "Grammar suggestion",
            offset=int(item.get("offset", 0)),
            length=int(item.get("length", 0)),
            original=item.get("original") or "",
            replacement=item.get("replacement"),
            issue_type=item.get("issue_type") or "grammar",
        )


def create_grammar_provider(provider: str, base_url: str) -> GrammarProvider:
    normalized = provider.strip().lower()
    if normalized == "languagetool":
        return LanguageToolProvider(base_url)
    if normalized == "korektor":
        return KorektorProvider(base_url)
    raise ValueError(f"Unsupported grammar provider: {provider}")

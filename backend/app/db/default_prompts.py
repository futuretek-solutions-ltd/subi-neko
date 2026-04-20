"""
Default prompt loader.

Prompts are stored as plain text files under backend/prompts/.
They use {TARGET_LANG_NAME} as a placeholder for the target language,
which is substituted at call time by the handlers.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


DEFAULT_TRANSLATION_PROMPT: str = _load("translate.txt")
DEFAULT_REPAIR_PROMPT: str = _load("repair.txt")
DEFAULT_LLM_REVIEW_PROMPT: str = _load("review.txt")

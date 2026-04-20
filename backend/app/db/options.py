"""
Options helper -- thin key/value store backed by the `options` table.

Sync API  (for job handlers running in threads):
    options.get(name, default)
    options.set(name, value)
    options.snapshot() -> AppOptions

Async API (for FastAPI routes):
    await options.aget(name, default)
    await options.aset(name, value)
    await options.asnapshot() -> AppOptions

Cache:
    All rows are loaded into memory on first access and kept until
    invalidated.  Writes update the cache immediately.
    Call options.invalidate() to force a full reload, or
    options.invalidate(name) to drop a single key.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import AsyncSessionLocal, SyncSessionLocal
from app.db.default_prompts import DEFAULT_REPAIR_PROMPT, DEFAULT_TRANSLATION_PROMPT, DEFAULT_LLM_REVIEW_PROMPT
from app.db.models import Option


# -- Typed options -------------------------------------------------------------

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_GRAMMAR_PROVIDERS = {"languagetool", "korektor", "none"}


@dataclass
class AppOptions:
    target_lang_name: str | None = None
    target_lang_code: str | None = None
    chunk_size: int = 100
    prepend_context_size: int = 5
    openai_api_base: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    openai_model_cheap: str = "gpt-5.4-mini"
    openai_model_better: str = "gpt-5.4"
    grammar_provider: str = "languagetool"
    grammar_provider_base_url: str = "http://localhost:8010"
    log_level: str = "INFO"
    job_worker_count: int = 4
    llm_review_always: bool = False
    llm_review_flagged_only: bool = True
    translation_prompt: str = DEFAULT_TRANSLATION_PROMPT
    repair_prompt: str = DEFAULT_REPAIR_PROMPT
    review_prompt: str = DEFAULT_LLM_REVIEW_PROMPT

    @classmethod
    def from_dict(cls, d: dict[str, str | None]) -> "AppOptions":
        raw_chunk_size = d.get("CHUNK_SIZE")
        raw_context_size = d.get("PREPEND_CONTEXT_SIZE")
        return cls(
            target_lang_name=d.get("TARGET_LANG_NAME"),
            target_lang_code=d.get("TARGET_LANG_CODE"),
            chunk_size=int(raw_chunk_size) if raw_chunk_size is not None else 100,
            prepend_context_size=int(raw_context_size) if raw_context_size is not None else 5,
            openai_api_base=d.get("OPENAI_API_BASE") or "https://api.openai.com/v1",
            openai_api_key=d.get("OPENAI_API_KEY"),
            openai_model_cheap=d.get("OPENAI_MODEL_CHEAP") or "gpt-5.4-mini",
            openai_model_better=d.get("OPENAI_MODEL_BETTER") or "gpt-5.4",
            grammar_provider=_validated_grammar_provider(d.get("GRAMMAR_PROVIDER")),
            grammar_provider_base_url=_validated_grammar_provider_base_url(
                d.get("GRAMMAR_PROVIDER_BASE_URL"),
                d.get("LANGUAGETOOL_URL"),
            ),
            log_level=_validated_log_level(d.get("LOG_LEVEL")),
            job_worker_count=_validated_worker_count(d.get("JOB_WORKER_COUNT")),
            llm_review_always=_validated_bool(d.get("LLM_REVIEW_ALWAYS")),
            llm_review_flagged_only=_validated_bool_default_true(d.get("LLM_REVIEW_FLAGGED_ONLY")),
            translation_prompt=d.get("TRANSLATION_PROMPT") or DEFAULT_TRANSLATION_PROMPT,
            repair_prompt=d.get("REPAIR_PROMPT") or DEFAULT_REPAIR_PROMPT,
            review_prompt=d.get("REVIEW_PROMPT") or DEFAULT_LLM_REVIEW_PROMPT,
        )

    def resolved_translation_prompt(self) -> str:
        lang = self.target_lang_name or "the target language"
        return self.translation_prompt.replace("{TARGET_LANG_NAME}", lang)

    def resolved_repair_prompt(self) -> str:
        lang = self.target_lang_name or "the target language"
        return self.repair_prompt.replace("{TARGET_LANG_NAME}", lang)

    def resolved_review_prompt(self) -> str:
        lang = self.target_lang_name or "the target language"
        return self.review_prompt.replace("{TARGET_LANG_NAME}", lang)


# -- Validation helpers --------------------------------------------------------

_logger = logging.getLogger(__name__)


def _validated_log_level(raw: str | None) -> str:
    if raw is None:
        return "INFO"
    normalized = raw.strip().upper()
    if normalized not in _VALID_LOG_LEVELS:
        _logger.warning("Invalid LOG_LEVEL %r, falling back to INFO", raw)
        return "INFO"
    return normalized


def _validated_grammar_provider(raw: str | None) -> str:
    if raw is None:
        return "languagetool"
    normalized = raw.strip().lower()
    if normalized not in _VALID_GRAMMAR_PROVIDERS:
        _logger.warning("Invalid GRAMMAR_PROVIDER %r, falling back to languagetool", raw)
        return "languagetool"
    return normalized


def _validated_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _validated_bool_default_true(raw: str | None) -> bool:
    """Like _validated_bool but defaults to True when key is absent."""
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _validated_grammar_provider_base_url(raw: str | None, legacy_raw: str | None) -> str:
    if raw is None and legacy_raw is None:
        return "http://localhost:8010"
    selected = raw if raw is not None else legacy_raw
    return selected.strip() if selected is not None else ""


def _validated_worker_count(raw: str | None) -> int:
    if raw is None:
        return 4
    try:
        n = int(raw)
    except ValueError:
        _logger.warning("Invalid JOB_WORKER_COUNT %r, falling back to 4", raw)
        return 4
    if n < 1:
        _logger.warning("JOB_WORKER_COUNT must be >= 1, got %d, falling back to 4", n)
        return 4
    if n > 32:
        _logger.warning("JOB_WORKER_COUNT capped at 32, got %d", n)
        return 32
    return n


# -- Change listeners (async only) ---------------------------------------------

ChangeListener = Callable[[str, str | None], Awaitable[None]]
_change_listeners: list[ChangeListener] = []


def register_change_listener(fn: ChangeListener) -> None:
    """Register a coroutine function called after every aset() write."""
    _change_listeners.append(fn)


# -- In-memory cache -----------------------------------------------------------
_cache: dict[str, str | None] = {}
_loaded = False
_lock = threading.Lock()


# -- Internal loaders ----------------------------------------------------------

def _load_sync() -> None:
    global _loaded
    with SyncSessionLocal() as session:
        rows = session.scalars(select(Option)).all()
    with _lock:
        for row in rows:
            _cache[row.name] = row.value
        _loaded = True


async def _load_async() -> None:
    global _loaded
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(Option))).all()
    with _lock:
        for row in rows:
            _cache[row.name] = row.value
        _loaded = True


# -- Sync API ------------------------------------------------------------------

def get(name: str, default: str | None = None) -> str | None:
    if not _loaded:
        _load_sync()
    with _lock:
        return _cache.get(name, default)


def set(name: str, value: str | None) -> None:
    now = datetime.utcnow().isoformat()
    with SyncSessionLocal() as session:
        session.execute(
            sqlite_insert(Option)
            .values(name=name, value=value, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["name"],
                set_={"value": value, "updated_at": now},
            )
        )
        session.commit()
    with _lock:
        _cache[name] = value


def snapshot() -> AppOptions:
    """Return a typed snapshot of current options for passing into JobContext."""
    if not _loaded:
        _load_sync()
    with _lock:
        return AppOptions.from_dict(dict(_cache))


# -- Async API -----------------------------------------------------------------

async def aget(name: str, default: str | None = None) -> str | None:
    if not _loaded:
        await _load_async()
    with _lock:
        return _cache.get(name, default)


async def aset(name: str, value: str | None) -> None:
    now = datetime.utcnow().isoformat()
    async with AsyncSessionLocal() as session:
        await session.execute(
            sqlite_insert(Option)
            .values(name=name, value=value, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["name"],
                set_={"value": value, "updated_at": now},
            )
        )
        await session.commit()
    with _lock:
        _cache[name] = value
    for listener in list(_change_listeners):
        try:
            await listener(name, value)
        except Exception:
            _logger.exception("Change listener failed for option %r", name)


async def asnapshot() -> AppOptions:
    """Async version of snapshot() for use in FastAPI routes."""
    if not _loaded:
        await _load_async()
    with _lock:
        return AppOptions.from_dict(dict(_cache))


# -- Cache control -------------------------------------------------------------

def invalidate(name: str | None = None) -> None:
    """Drop one key or the entire cache (forces reload on next access)."""
    global _loaded
    with _lock:
        if name is None:
            _cache.clear()
            _loaded = False
        else:
            _cache.pop(name, None)

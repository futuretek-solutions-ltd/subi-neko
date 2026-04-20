from __future__ import annotations

from typing import Any, Callable

from app.jobs.context import JobContext, JobResult, ProgressFn

# Handler: plain synchronous function run in a thread by the job manager.
HandlerFn = Callable[[dict[str, Any], JobContext, ProgressFn], JobResult]

_registry: dict[str, HandlerFn] = {}


def register_job_handler(job_type: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator to register a sync handler for a job type."""
    def decorator(fn: HandlerFn) -> HandlerFn:
        _registry[job_type] = fn
        return fn
    return decorator


def get_handler(job_type: str) -> HandlerFn | None:
    return _registry.get(job_type)


def list_job_types() -> list[str]:
    return list(_registry.keys())

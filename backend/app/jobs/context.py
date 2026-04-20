from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypedDict

from app.db.options import AppOptions

# Sync progress callback — safe to call from a thread
ProgressFn = Callable[[float, str], None]


@dataclass
class JobContext:
    import_root: Path
    output_root: Path
    options: AppOptions = field(default_factory=AppOptions)


class JobResult(TypedDict):
    status: str          # "succeeded" | "failed"
    result: dict | None
    error_code: str | None
    error_message: str | None

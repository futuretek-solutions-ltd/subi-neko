from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"


@dataclass
class ScheduledTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    job_type: str = ""
    project_id: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    trigger_type: TriggerType = TriggerType.INTERVAL
    trigger_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_triggered_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "job_type": self.job_type,
            "project_id": self.project_id,
            "payload": self.payload,
            "trigger_type": self.trigger_type.value,
            "trigger_config": self.trigger_config,
            "enabled": self.enabled,
            "last_triggered_at": self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            "created_at": self.created_at.isoformat(),
        }

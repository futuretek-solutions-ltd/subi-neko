from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class JobProgress:
    """In-memory only — tracks real-time progress of a running job.

    The DB record (JobRecord) is the source of truth for status/result.
    This exists only to hold transient progress state between DB writes.
    """
    job_id: int
    job_type: str
    progress: float = 0.0
    message: str = ""
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "progress": self.progress,
            "message": self.message,
            "updated_at": self.updated_at.isoformat(),
        }

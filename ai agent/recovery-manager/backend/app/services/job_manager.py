"""In-memory and thread-safe job tracking service for async background operations."""

import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Job:
    id: str
    job_type: str
    status: str  # "pending", "running", "completed", "failed"
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    progress: float = 0.0  # 0.0 to 1.0
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobManager:
    """Thread-safe background job manager."""

    def __init__(self, max_history: int = 500):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_history = max_history

    def create_job(self, job_type: str, metadata: Optional[Dict[str, Any]] = None) -> Job:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        job = Job(
            id=job_id,
            job_type=job_type,
            status="pending",
            created_at=now,
            updated_at=now,
            progress=0.0,
            metadata=metadata or {},
        )
        with self._lock:
            # Evict oldest if exceeding max history
            if len(self._jobs) >= self._max_history:
                oldest_id = next(iter(self._jobs))
                del self._jobs[oldest_id]
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            now = datetime.now(timezone.utc).isoformat()
            job.updated_at = now
            if status is not None:
                job.status = status
                if status in ("completed", "failed"):
                    job.completed_at = now
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            return job


job_manager = JobManager()

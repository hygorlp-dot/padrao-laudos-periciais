from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    status: JobStatus
    progress: int | None
    error: object = None
    result: object = None

    @classmethod
    def new(cls, progress=None):
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("progress deve estar entre 0 e 100")
        return cls(str(uuid4()), JobStatus.QUEUED, progress)

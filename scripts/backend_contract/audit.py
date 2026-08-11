from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    correlation_id: str
    created_at: str
    case_id: str | None
    artifact_id: str | None
    summary: str

    @classmethod
    def create(cls, event_type, correlation_id, summary, case_id=None, artifact_id=None):
        if not event_type or not correlation_id or not summary:
            raise ValueError("Evento de auditoria incompleto")
        return cls(
            str(uuid4()), event_type, correlation_id,
            datetime.now(timezone.utc).isoformat(), case_id, artifact_id, summary,
        )


class AuditLog:
    def __init__(self):
        self._events = []

    def append(self, event):
        self._events.append(event)

    @property
    def events(self):
        return tuple(self._events)

    def snapshot(self):
        return deepcopy(self._events)

    def restore(self, snapshot):
        self._events = snapshot

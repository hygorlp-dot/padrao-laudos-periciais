"""Non-blocking lifecycle adapter; Claw3D never affects domain results."""
from __future__ import annotations

from contextlib import contextmanager
from .state import PresenceStore


class AgentPresenceSink:
    def set_state(self, agent_id: str, state: str) -> None:
        raise NotImplementedError

    def heartbeat(self, agent_id: str) -> None:
        raise NotImplementedError


class Claw3DPresenceSink(AgentPresenceSink):
    def __init__(self, store: PresenceStore | None = None):
        self.store = store or PresenceStore.from_environment()

    def set_state(self, agent_id: str, state: str) -> None:
        self.store.set_state(agent_id, state)

    def heartbeat(self, agent_id: str) -> None:
        self.store.heartbeat(agent_id)


def _safe_set(sink: AgentPresenceSink, agent_id: str, state: str) -> None:
    try:
        sink.set_state(agent_id, state)
    except Exception:
        # Observability must never propagate into the workflow/Core.
        return


@contextmanager
def agent_lifecycle(sink: AgentPresenceSink, agent_id: str):
    _safe_set(sink, agent_id, "working")
    try:
        yield
    except BaseException:
        _safe_set(sink, agent_id, "error")
        raise
    else:
        _safe_set(sink, agent_id, "idle")

"""Local, non-authoritative Claw3D live presence integration."""

from .bridge import PresenceBridge
from .hooks import AgentPresenceSink, Claw3DPresenceSink, agent_lifecycle
from .state import AGENTS, PresenceStore

__all__ = ["AGENTS", "AgentPresenceSink", "Claw3DPresenceSink", "PresenceBridge", "PresenceStore", "agent_lifecycle"]

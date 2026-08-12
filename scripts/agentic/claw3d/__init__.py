"""Local, non-authoritative Claw3D live presence integration."""

from .bridge import PresenceBridge
from .hooks import AgentPresenceSink, Claw3DPresenceSink, agent_lifecycle
from .state import AGENTS, PresenceStore
from .runner import ClaudeManagedRunner, ExecutionResult, ManagedAgentRunner

__all__ = ["AGENTS", "AgentPresenceSink", "ClaudeManagedRunner", "Claw3DPresenceSink", "ExecutionResult", "ManagedAgentRunner", "PresenceBridge", "PresenceStore", "agent_lifecycle"]

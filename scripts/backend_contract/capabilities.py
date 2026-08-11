from dataclasses import dataclass
from enum import StrEnum

from .errors import DomainError


class CapabilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: CapabilityStatus
    reason: str


@dataclass(frozen=True, slots=True)
class EvidenceLimitation:
    subject: str
    reason: str


class CapabilityRegistry:
    def __init__(self):
        self._items = {}

    def register(self, name, status, reason):
        if not name or not reason:
            raise ValueError("Capability exige nome e justificativa")
        self._items[name] = Capability(name, status, reason)

    def require(self, name):
        try:
            return self._items[name]
        except KeyError as exc:
            raise DomainError(f"Capability não registrada: {name}") from exc

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from uuid import uuid4

from .models import ArtifactStatus


def _deep_freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return deepcopy(value)


class RevisionSource(StrEnum):
    SOURCE = "SOURCE"
    AI = "AI"
    ENGINE = "ENGINE"
    PROFESSIONAL = "PROFESSIONAL"


@dataclass(frozen=True, slots=True)
class Revision:
    revision_id: str
    artifact_id: str
    revision: int
    created_at: str
    supersedes: str | None
    status: ArtifactStatus
    source: RevisionSource
    payload: MappingProxyType


class RevisionStore:
    def __init__(self):
        self._items = {}

    def append(self, artifact_id, payload, source):
        history = self._items.setdefault(artifact_id, [])
        supersedes = history[-1].revision_id if history else None
        if history:
            history[-1] = replace(history[-1], status=ArtifactStatus.SUPERSEDED)
        item = Revision(
            revision_id=str(uuid4()), artifact_id=artifact_id,
            revision=len(history) + 1, created_at=datetime.now(timezone.utc).isoformat(),
            supersedes=supersedes, status=ArtifactStatus.CURRENT, source=source,
            payload=_deep_freeze(payload),
        )
        history.append(item)
        return item

    def history(self, artifact_id):
        return tuple(self._items.get(artifact_id, ()))

    def snapshot(self):
        return {
            artifact_id: list(history)
            for artifact_id, history in self._items.items()
        }

    def restore(self, snapshot):
        self._items = snapshot


class Authority(StrEnum):
    SOURCE_VALUE = "SOURCE_VALUE"
    AI_PROPOSAL = "AI_PROPOSAL"
    ENGINE_DECISION = "ENGINE_DECISION"
    PROFESSIONAL_OVERRIDE = "PROFESSIONAL_OVERRIDE"
    EFFECTIVE_VALUE = "EFFECTIVE_VALUE"


@dataclass(frozen=True, slots=True)
class ValueEntry:
    authority: Authority
    value: object
    created_at: str
    reason: str | None = None


class ValueHistory:
    def __init__(self):
        self._entries = []

    @property
    def entries(self):
        return tuple(self._entries)

    def _append(self, authority, value, reason=None):
        if authority is Authority.EFFECTIVE_VALUE:
            raise ValueError("EFFECTIVE_VALUE é derivado, não armazenado")
        if authority is Authority.PROFESSIONAL_OVERRIDE and not reason:
            raise ValueError("Professional Override exige justificativa")
        entry = ValueEntry(authority, _deep_freeze(value), datetime.now(timezone.utc).isoformat(), reason)
        self._entries.append(entry)
        return entry

    def record_source(self, value):
        return self._append(Authority.SOURCE_VALUE, value)

    def propose_ai(self, value):
        return self._append(Authority.AI_PROPOSAL, value)

    def decide_engine(self, value, reason=None):
        return self._append(Authority.ENGINE_DECISION, value, reason)

    def override_professional(self, value, reason):
        return self._append(Authority.PROFESSIONAL_OVERRIDE, value, reason)

    def effective(self):
        precedence = (
            Authority.PROFESSIONAL_OVERRIDE,
            Authority.ENGINE_DECISION,
            Authority.SOURCE_VALUE,
        )
        for authority in precedence:
            for entry in reversed(self._entries):
                if entry.authority is authority:
                    return entry
        raise ValueError("Nenhum valor efetivo disponível")

    def pending_proposals(self):
        last_decision = max(
            (
                index for index, entry in enumerate(self._entries)
                if entry.authority in {Authority.ENGINE_DECISION, Authority.PROFESSIONAL_OVERRIDE}
            ),
            default=-1,
        )
        return tuple(
            entry for entry in self._entries[last_decision + 1:]
            if entry.authority is Authority.AI_PROPOSAL
        )

    def snapshot(self):
        return list(self._entries)

    def restore(self, snapshot):
        if not isinstance(snapshot, (list, tuple)) or not all(isinstance(entry, ValueEntry) for entry in snapshot):
            raise ValueError("Snapshot de ValueHistory inválido")
        self._entries = list(snapshot)

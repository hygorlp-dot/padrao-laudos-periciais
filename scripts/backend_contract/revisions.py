from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import hmac
import json
from decimal import Decimal
from types import MappingProxyType
from uuid import uuid4

from .models import ArtifactStatus


def _deep_freeze(value):
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise TypeError("Tipo de valor não suportado: chave não textual")
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) in {list, tuple}:
        return tuple(_deep_freeze(item) for item in value)
    if type(value) in {set, frozenset}:
        return frozenset(_deep_freeze(item) for item in value)
    if value is None or type(value) in {bool, int, float, str, bytes, Decimal}:
        return deepcopy(value)
    raise TypeError(f"Tipo de valor não suportado: {type(value).__name__}")


def _canonical(value):
    if isinstance(value, MappingProxyType):
        return ["map", [[key, _canonical(item)] for key, item in sorted(value.items())]]
    if isinstance(value, tuple):
        return ["tuple", [_canonical(item) for item in value]]
    if isinstance(value, frozenset):
        items = [_canonical(item) for item in value]
        return ["set", sorted(items, key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True))]
    if isinstance(value, ValueEntry):
        return ["entry", value.authority.value, _canonical(value.value), value.created_at, value.reason]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, Decimal):
        return ["decimal", str(value)]
    if value is None or isinstance(value, (bool, int, float, str)):
        return [type(value).__name__, value]
    raise TypeError(f"Tipo de valor não suportado: {type(value).__name__}")


def _snapshot_payload(history_id, entries):
    return json.dumps(
        [history_id, [_canonical(entry) for entry in entries]],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


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


@dataclass(frozen=True, slots=True)
class ValueHistorySnapshot:
    history_id: str
    entries: tuple[ValueEntry, ...]
    signature: str


class ValueHistory:
    def __init__(self):
        self._entries = []
        self._history_id = str(uuid4())
        self._snapshot_key = uuid4().bytes

    @property
    def entries(self):
        return tuple(self._entries)

    def _append(self, authority, value, reason=None):
        if authority is Authority.EFFECTIVE_VALUE:
            raise ValueError("EFFECTIVE_VALUE é derivado, não armazenado")
        if reason is not None and type(reason) is not str:
            raise TypeError("justificativa deve ser texto imutável")
        if authority is Authority.PROFESSIONAL_OVERRIDE and (not reason or not reason.strip()):
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
        entries = tuple(self._entries)
        signature = hmac.new(self._snapshot_key, _snapshot_payload(self._history_id, entries), hashlib.sha256).hexdigest()
        return ValueHistorySnapshot(self._history_id, entries, signature)

    def restore(self, snapshot):
        if not isinstance(snapshot, ValueHistorySnapshot) or snapshot.history_id != self._history_id:
            raise ValueError("Snapshot de ValueHistory inválido")
        try:
            expected = hmac.new(
                self._snapshot_key,
                _snapshot_payload(snapshot.history_id, snapshot.entries),
                hashlib.sha256,
            ).hexdigest()
        except (TypeError, ValueError) as exc:
            raise ValueError("Snapshot de ValueHistory inválido") from exc
        if not hmac.compare_digest(snapshot.signature, expected):
            raise ValueError("Snapshot de ValueHistory inválido")
        self._entries = list(snapshot.entries)

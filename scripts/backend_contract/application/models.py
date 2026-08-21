"""Registros técnicos mínimos da Application Layer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _timestamp(value: str, field: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field} inválido")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} exige timezone")
    return value


def _freeze_payload(value, active=None):
    active = set() if active is None else active
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("payload JSON não aceita número não finito")
        return value
    if type(value) not in {list, dict}:
        raise TypeError(f"payload JSON incompatível: {type(value).__name__}")
    if id(value) in active:
        raise ValueError("payload JSON cíclico não suportado")
    active.add(id(value))
    try:
        if type(value) is list:
            return tuple(_freeze_payload(item, active) for item in value)
        if not all(type(key) is str for key in value):
            raise TypeError("payload JSON exige chaves textuais")
        return MappingProxyType(
            {key: _freeze_payload(item, active) for key, item in value.items()}
        )
    finally:
        active.remove(id(value))


def thaw_payload(value):
    """Retorna uma cópia JSON mutável sem alterar o registro persistido."""
    if isinstance(value, MappingProxyType):
        return {key: thaw_payload(item) for key, item in value.items()}
    if type(value) is tuple:
        return [thaw_payload(item) for item in value]
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError(f"payload congelado inválido: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: UUID

    def __post_init__(self):
        if type(self.value) is not UUID:
            raise TypeError("WorkspaceId exige UUID")

    @classmethod
    def parse(cls, value: str) -> WorkspaceId:
        if type(value) is not str:
            raise TypeError("workspace_id deve ser texto UUID")
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PericiaWorkspace:
    workspace_id: WorkspaceId
    name: str
    created_at: str

    def __post_init__(self):
        if type(self.workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("name inválido")
        _timestamp(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ArtifactRevision:
    workspace_id: WorkspaceId
    artifact_kind: str
    artifact_id: str
    revision_id: str
    revision: int
    created_at: str
    checksum_sha256: str
    payload: object

    def __post_init__(self):
        if type(self.workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        for field, value in (
            ("artifact_kind", self.artifact_kind),
            ("artifact_id", self.artifact_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field} inválido")
        if type(self.revision_id) is not str:
            raise TypeError("revision_id inválido")
        try:
            UUID(self.revision_id)
        except ValueError as exc:
            raise ValueError("revision_id inválido") from exc
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision inválida")
        _timestamp(self.created_at, "created_at")
        if (
            type(self.checksum_sha256) is not str
            or _SHA256.fullmatch(self.checksum_sha256) is None
        ):
            raise ValueError("checksum_sha256 inválido")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))

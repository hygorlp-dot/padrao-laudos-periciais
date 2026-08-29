"""Registros técnicos mínimos da Application Layer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from uuid import UUID


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validated_text(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} inválido")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contém Unicode inválido") from exc
    return value


def _timestamp(value: str, field: str) -> str:
    _validated_text(value, field)
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


def canonical_payload_json(value) -> str:
    """Codifica um payload JSON validado sem perder Unicode ou ordem de listas."""
    try:
        mutable = thaw_payload(_freeze_payload(value))
        encoded = json.dumps(
            mutable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded.encode("utf-8")
        return encoded
    except RecursionError as exc:
        raise ValueError("payload JSON excede profundidade suportada") from exc
    except UnicodeEncodeError as exc:
        raise ValueError("payload JSON contém Unicode inválido") from exc


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
class PrivateContentId:
    value: UUID

    def __post_init__(self):
        if type(self.value) is not UUID:
            raise TypeError("PrivateContentId exige UUID")

    @classmethod
    def parse(cls, value: str) -> PrivateContentId:
        if type(value) is not str:
            raise TypeError("content_id deve ser texto UUID canônico")
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("content_id inválido") from exc
        if str(parsed) != value:
            raise ValueError("content_id deve ser UUID canônico")
        return cls(parsed)

    def __str__(self) -> str:
        return str(self.value)


class PrivateContentOrigin(Enum):
    LOCAL_IMPORT = "LOCAL_IMPORT"
    USER_IMPORT = "USER_IMPORT"


@dataclass(frozen=True, slots=True)
class PrivateContentMetadata:
    workspace_id: WorkspaceId
    content_id: PrivateContentId
    original_filename: str
    byte_size: int
    checksum_sha256: str
    media_type: str | None
    imported_at: str
    origin: PrivateContentOrigin

    def __post_init__(self):
        if type(self.workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if type(self.content_id) is not PrivateContentId:
            raise TypeError("content_id inválido")
        _validated_text(self.original_filename, "original_filename")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("byte_size inválido")
        if (
            type(self.checksum_sha256) is not str
            or _SHA256.fullmatch(self.checksum_sha256) is None
        ):
            raise ValueError("checksum_sha256 inválido")
        if self.media_type is not None:
            _validated_text(self.media_type, "media_type")
        _timestamp(self.imported_at, "imported_at")
        if type(self.origin) is not PrivateContentOrigin:
            raise TypeError("origin inválida")


@dataclass(frozen=True, slots=True)
class PrivateContent:
    metadata: PrivateContentMetadata
    content: bytes

    def __post_init__(self):
        if type(self.metadata) is not PrivateContentMetadata:
            raise TypeError("metadata de conteúdo privado inválida")
        if type(self.content) is not bytes:
            raise TypeError("conteúdo privado exige bytes")
        if len(self.content) != self.metadata.byte_size:
            raise ValueError("conteúdo privado diverge do tamanho declarado")
        checksum = hashlib.sha256(self.content).hexdigest()
        if checksum != self.metadata.checksum_sha256:
            raise ValueError("conteúdo privado diverge do checksum declarado")


@dataclass(frozen=True, slots=True)
class PericiaWorkspace:
    workspace_id: WorkspaceId
    name: str
    created_at: str

    def __post_init__(self):
        if type(self.workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        _validated_text(self.name, "name")
        _timestamp(self.created_at, "created_at")


_PROCESS_CASE_FIELDS = (
    "numero_processo",
    "ramo_justica",
    "tribunal",
    "vara",
    "municipio_sede",
    "subsecao_judiciaria",
    "comarca_municipio",
    "uf",
    "parte_requerente",
    "parte_requerida",
)


def _process_case_text(value: str, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} deve ser texto")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contém Unicode inválido") from exc
    return value


@dataclass(frozen=True, slots=True)
class ProcessCaseData:
    numero_processo: str
    ramo_justica: str
    tribunal: str
    vara: str
    municipio_sede: str
    subsecao_judiciaria: str
    comarca_municipio: str
    uf: str
    parte_requerente: str
    parte_requerida: str

    def __post_init__(self):
        for field in _PROCESS_CASE_FIELDS:
            _process_case_text(getattr(self, field), field)

    @classmethod
    def empty(cls) -> ProcessCaseData:
        return cls(**{field: "" for field in _PROCESS_CASE_FIELDS})

    @classmethod
    def from_mapping(cls, value: object) -> ProcessCaseData:
        derived_fields = {"municipio_sede", "subsecao_judiciaria"}
        legacy_fields = set(_PROCESS_CASE_FIELDS) - derived_fields
        oldest_fields = legacy_fields - {"ramo_justica"}
        if type(value) is not dict or frozenset(value) not in {
            frozenset(_PROCESS_CASE_FIELDS),
            frozenset(legacy_fields),
            frozenset(oldest_fields),
        }:
            raise ValueError("dados processuais exigem campos exatos")
        normalized = dict(value)
        normalized.setdefault("ramo_justica", "")
        normalized.setdefault("municipio_sede", "")
        normalized.setdefault("subsecao_judiciaria", "")
        return cls(**{field: normalized[field] for field in _PROCESS_CASE_FIELDS})

    def as_dict(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in _PROCESS_CASE_FIELDS}


@dataclass(frozen=True, slots=True)
class ProcessCaseSnapshot:
    workspace_id: WorkspaceId
    revision: int | None
    updated_at: str | None
    data: ProcessCaseData

    def __post_init__(self):
        if type(self.workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if self.revision is not None and (
            type(self.revision) is not int or self.revision < 1
        ):
            raise ValueError("revision inválida")
        if self.updated_at is not None:
            _timestamp(self.updated_at, "updated_at")
        if (self.revision is None) != (self.updated_at is None):
            raise ValueError("metadados de revisão incompletos")
        if type(self.data) is not ProcessCaseData:
            raise TypeError("dados processuais inválidos")


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
            _validated_text(value, field)
        if type(self.revision_id) is not str:
            raise TypeError("revision_id inválido")
        try:
            canonical_revision_id = str(UUID(self.revision_id))
        except ValueError as exc:
            raise ValueError("revision_id inválido") from exc
        object.__setattr__(self, "revision_id", canonical_revision_id)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision inválida")
        _timestamp(self.created_at, "created_at")
        if (
            type(self.checksum_sha256) is not str
            or _SHA256.fullmatch(self.checksum_sha256) is None
        ):
            raise ValueError("checksum_sha256 inválido")
        try:
            frozen_payload = _freeze_payload(self.payload)
        except RecursionError as exc:
            raise ValueError("payload JSON excede profundidade suportada") from exc
        object.__setattr__(self, "payload", frozen_payload)

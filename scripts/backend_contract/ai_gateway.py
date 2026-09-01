"""Contratos imutáveis do AI Gateway; nenhuma autoridade profissional nasce aqui."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID


_SHA256 = re.compile(r"[0-9a-f]{64}")
_SECRET_FIELDS = frozenset(
    {"api_key", "apikey", "secret", "authorization", "bearer", "bearer_token", "password", "credential"}
)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} inválido")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contém Unicode inválido") from exc
    return value


def _uuid(value: object, field: str, *, version_four: bool = False) -> str:
    _text(value, field)
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} exige UUID") from exc
    if str(parsed) != value or (version_four and parsed.version != 4):
        raise ValueError(f"{field} exige UUID canônico" + (" v4" if version_four else ""))
    return value


def _sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} exige sha256 hexadecimal")
    return value


def _timestamp(value: object, field: str) -> str:
    _text(value, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} exige timezone")
    return value


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    return normalized in _SECRET_FIELDS or any(part in _SECRET_FIELDS for part in normalized.split("_"))


def _freeze_json(value: object, *, reject_secrets: bool = False, active: set[int] | None = None):
    active = set() if active is None else active
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("payload JSON exige números finitos")
        return value
    if type(value) not in {dict, list, tuple, MappingProxyType}:
        raise TypeError(f"payload JSON incompatível: {type(value).__name__}")
    if id(value) in active:
        raise ValueError("payload JSON cíclico")
    active.add(id(value))
    try:
        if type(value) in {list, tuple}:
            return tuple(_freeze_json(item, reject_secrets=reject_secrets, active=active) for item in value)
        if not all(type(key) is str for key in value):
            raise TypeError("payload JSON exige chaves textuais")
        if reject_secrets and any(_secret_key(key) for key in value):
            raise ValueError("payload de IA não pode persistir campo secret")
        return MappingProxyType(
            {
                key: _freeze_json(item, reject_secrets=reject_secrets, active=active)
                for key, item in value.items()
            }
        )
    finally:
        active.remove(id(value))


class EgressClass(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    REMOTE_SANITIZED = "REMOTE_SANITIZED"
    REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED = "REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED"


class EgressDenied(PermissionError):
    """Negação estável e sem conteúdo privado."""


@dataclass(frozen=True, slots=True)
class SourceRevisionRef:
    workspace_id: str
    document_id: str
    revision_id: str
    sha256: str
    locator: str

    def __post_init__(self) -> None:
        _uuid(self.workspace_id, "workspace_id")
        _text(self.document_id, "document_id")
        _text(self.revision_id, "revision_id")
        _sha256(self.sha256, "sha256")
        _text(self.locator, "locator")


@dataclass(frozen=True, slots=True)
class AIContextSegment:
    source: SourceRevisionRef
    content: str

    def __post_init__(self) -> None:
        if type(self.source) is not SourceRevisionRef:
            raise TypeError("source inválida")
        _text(self.content, "content")


@dataclass(frozen=True, slots=True)
class EgressManifest:
    workspace_id: str
    egress_class: EgressClass
    source_refs: tuple[SourceRevisionRef, ...]
    redaction_manifest: tuple[str, ...]
    contains_private_data: bool
    explicitly_authorized: bool

    def __post_init__(self) -> None:
        _uuid(self.workspace_id, "workspace_id")
        if type(self.egress_class) is not EgressClass:
            raise TypeError("egress_class inválida")
        if type(self.source_refs) is not tuple or any(type(item) is not SourceRevisionRef for item in self.source_refs):
            raise TypeError("source_refs inválidas")
        if type(self.redaction_manifest) is not tuple:
            raise TypeError("redaction_manifest inválido")
        for item in self.redaction_manifest:
            _text(item, "redaction_manifest")
        if type(self.contains_private_data) is not bool or type(self.explicitly_authorized) is not bool:
            raise TypeError("flags de egress inválidas")


@dataclass(frozen=True, slots=True)
class AIModelProfile:
    profile_id: str
    provider: str
    model: str
    max_input_tokens: int
    max_output_tokens: int
    cost_ceiling_microusd: int
    timeout_seconds: float
    structured_output_required: bool
    model_parameters: object

    def __post_init__(self) -> None:
        for field in ("profile_id", "provider", "model"):
            _text(getattr(self, field), field)
        for field in ("max_input_tokens", "max_output_tokens", "cost_ceiling_microusd"):
            value = getattr(self, field)
            if type(value) is not int or value < 0 or (field != "cost_ceiling_microusd" and value == 0):
                raise ValueError(f"{field} inválido")
        if type(self.timeout_seconds) not in {int, float} or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds inválido")
        if type(self.structured_output_required) is not bool:
            raise TypeError("structured_output_required inválido")
        object.__setattr__(self, "model_parameters", _freeze_json(self.model_parameters, reject_secrets=True))


@dataclass(frozen=True, slots=True)
class UsageRecord:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int | None

    def __post_init__(self) -> None:
        for field in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} inválido")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens excede input_tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens diverge de input_tokens + output_tokens")
        if self.estimated_cost_microusd is not None and (
            type(self.estimated_cost_microusd) is not int or self.estimated_cost_microusd < 0
        ):
            raise ValueError("estimated_cost_microusd inválido")


@dataclass(frozen=True, slots=True)
class AIRequest:
    workspace_id: str
    task_type: str
    task_instructions: str
    prompt_template_version: str
    prompt_template_hash: str
    structured_output_schema: object
    structured_output_schema_hash: str
    context: tuple[AIContextSegment, ...]
    context_manifest_hash: str
    egress_manifest: EgressManifest

    def __post_init__(self) -> None:
        _uuid(self.workspace_id, "workspace_id")
        _text(self.task_type, "task_type")
        _text(self.task_instructions, "task_instructions")
        _text(self.prompt_template_version, "prompt_template_version")
        _sha256(self.prompt_template_hash, "prompt_template_hash")
        _sha256(self.structured_output_schema_hash, "structured_output_schema_hash")
        _sha256(self.context_manifest_hash, "context_manifest_hash")
        if type(self.context) is not tuple or any(type(item) is not AIContextSegment for item in self.context):
            raise TypeError("context inválido")
        if type(self.egress_manifest) is not EgressManifest:
            raise TypeError("egress_manifest inválido")
        object.__setattr__(self, "structured_output_schema", _freeze_json(self.structured_output_schema, reject_secrets=True))


@dataclass(frozen=True, slots=True)
class AIResponse:
    provider: str
    model: str
    provider_response_id: str | None
    payload: object
    response_hash: str
    usage: UsageRecord | None
    latency_ms: int
    refusal_state: str

    def __post_init__(self) -> None:
        for field in ("provider", "model", "refusal_state"):
            _text(getattr(self, field), field)
        if self.provider_response_id is not None:
            _text(self.provider_response_id, "provider_response_id")
        _sha256(self.response_hash, "response_hash")
        if self.usage is not None and type(self.usage) is not UsageRecord:
            raise TypeError("usage inválido")
        if type(self.latency_ms) is not int or self.latency_ms < 0:
            raise ValueError("latency_ms inválido")
        object.__setattr__(self, "payload", _freeze_json(self.payload, reject_secrets=True))


@dataclass(frozen=True, slots=True)
class AIProposal:
    proposal_id: str
    workspace_id: str
    task_type: str
    source_refs: tuple[SourceRevisionRef, ...]
    proposal_payload: object
    provider: str
    model: str
    run_id: str
    created_at: str
    confidence_score: float | None

    def __post_init__(self) -> None:
        _uuid(self.proposal_id, "proposal_id", version_four=True)
        _uuid(self.workspace_id, "workspace_id")
        _uuid(self.run_id, "run_id", version_four=True)
        for field in ("task_type", "provider", "model"):
            _text(getattr(self, field), field)
        _timestamp(self.created_at, "created_at")
        if type(self.source_refs) is not tuple or any(type(item) is not SourceRevisionRef for item in self.source_refs):
            raise TypeError("source_refs inválidas")
        if self.confidence_score is not None and (
            type(self.confidence_score) not in {int, float}
            or not math.isfinite(self.confidence_score)
            or not 0 <= self.confidence_score <= 1
        ):
            raise ValueError("confidence_score inválido")
        object.__setattr__(self, "proposal_payload", _freeze_json(self.proposal_payload, reject_secrets=True))


@dataclass(frozen=True, slots=True)
class AIRun:
    run_id: str
    workspace_id: str
    task_type: str
    provider: str
    model: str
    model_parameters: object
    prompt_template_version: str
    prompt_template_hash: str
    structured_output_schema_hash: str
    context_manifest_hash: str
    source_refs: tuple[SourceRevisionRef, ...]
    egress_class: EgressClass
    redaction_manifest: tuple[str, ...]
    usage: UsageRecord | None
    latency_ms: int
    provider_response_id: str | None
    response_hash: str | None
    refusal_state: str
    error_classification: str | None
    proposal_ids: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        _uuid(self.run_id, "run_id", version_four=True)
        _uuid(self.workspace_id, "workspace_id")
        for field in ("task_type", "provider", "model", "prompt_template_version", "refusal_state"):
            _text(getattr(self, field), field)
        for field in ("prompt_template_hash", "structured_output_schema_hash", "context_manifest_hash"):
            _sha256(getattr(self, field), field)
        if self.response_hash is not None:
            _sha256(self.response_hash, "response_hash")
        if self.provider_response_id is not None:
            _text(self.provider_response_id, "provider_response_id")
        if self.error_classification is not None:
            _text(self.error_classification, "error_classification")
        if type(self.latency_ms) is not int or self.latency_ms < 0:
            raise ValueError("latency_ms inválido")
        if self.usage is not None and type(self.usage) is not UsageRecord:
            raise TypeError("usage inválido")
        if type(self.egress_class) is not EgressClass:
            raise TypeError("egress_class inválida")
        if type(self.source_refs) is not tuple or any(type(item) is not SourceRevisionRef for item in self.source_refs):
            raise TypeError("source_refs inválidas")
        if type(self.redaction_manifest) is not tuple or any(type(item) is not str for item in self.redaction_manifest):
            raise TypeError("redaction_manifest inválido")
        if type(self.proposal_ids) is not tuple:
            raise TypeError("proposal_ids inválidos")
        for proposal_id in self.proposal_ids:
            _uuid(proposal_id, "proposal_id", version_four=True)
        _timestamp(self.created_at, "created_at")
        object.__setattr__(self, "model_parameters", _freeze_json(self.model_parameters, reject_secrets=True))


class EgressPolicy:
    def __init__(self, *, remote_sanitized_enabled: bool = False, remote_private_enabled: bool = False):
        if type(remote_sanitized_enabled) is not bool or type(remote_private_enabled) is not bool:
            raise TypeError("configuração de egress inválida")
        self._remote_sanitized_enabled = remote_sanitized_enabled
        self._remote_private_enabled = remote_private_enabled

    def authorize(self, request: AIRequest) -> None:
        if type(request) is not AIRequest:
            raise TypeError("request inválido")
        manifest = request.egress_manifest
        if manifest.workspace_id != request.workspace_id:
            raise EgressDenied("CROSS_WORKSPACE_AI_CONTEXT")
        context_refs = tuple(segment.source for segment in request.context)
        if context_refs != manifest.source_refs or any(ref.workspace_id != request.workspace_id for ref in context_refs):
            raise ValueError("workspace/source manifest mismatch")
        if manifest.egress_class is EgressClass.LOCAL_ONLY:
            return
        if manifest.egress_class is EgressClass.REMOTE_SANITIZED:
            if not self._remote_sanitized_enabled:
                raise EgressDenied("REMOTE_AI_EGRESS_DENIED")
            if manifest.contains_private_data or manifest.explicitly_authorized:
                raise EgressDenied("REMOTE_SANITIZED_MANIFEST_INVALID")
            return
        if not self._remote_private_enabled or not manifest.explicitly_authorized:
            raise EgressDenied("PRIVATE_EGRESS_NOT_AUTHORIZED")

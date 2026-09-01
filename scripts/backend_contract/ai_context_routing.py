"""Deterministic local context selection, model routing, and cache identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType

from .ai_gateway import AIContextSegment, AIModelProfile, AIRequest, SourceRevisionRef


class ContextPriority(IntEnum):
    EXPLICIT_TARGET = 1
    REVIEWED_VALUE = 2
    EXACT_EVIDENCE = 3
    CONTRARY_EVIDENCE = 4
    PROCEDURAL_CONTEXT = 5
    SUPPORTING = 6


class ContextBudgetExceeded(ValueError):
    """Required context cannot fit without a silent semantic omission."""


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    segment: AIContextSegment
    priority: ContextPriority
    estimated_tokens: int
    relevance_micros: int

    def __post_init__(self) -> None:
        if type(self.priority) is not ContextPriority:
            raise TypeError("context priority invalid")
        if type(self.estimated_tokens) is not int or self.estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be positive")
        if self.estimated_tokens != estimate_context_tokens(self.segment.content):
            raise ValueError("estimated_tokens diverges from deterministic content estimate")
        if type(self.relevance_micros) is not int or not 0 <= self.relevance_micros <= 1_000_000:
            raise ValueError("relevance_micros invalid")


def estimate_context_tokens(content: str) -> int:
    """Deterministic conservative local estimate; provider usage remains authoritative telemetry."""
    if type(content) is not str or not content:
        raise ValueError("context content invalid")
    return max(1, (len(content.encode("utf-8")) + 3) // 4)


@dataclass(frozen=True, slots=True)
class ContextSelectionRequest:
    workspace_id: str
    max_input_tokens: int

    def __post_init__(self) -> None:
        if type(self.workspace_id) is not str or not self.workspace_id:
            raise ValueError("workspace_id invalid")
        if type(self.max_input_tokens) is not int or self.max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be positive")


@dataclass(frozen=True, slots=True)
class ContextSelection:
    segments: tuple[AIContextSegment, ...]
    source_refs: tuple[SourceRevisionRef, ...]
    total_estimated_tokens: int


def _candidate_key(candidate: ContextCandidate) -> tuple[object, ...]:
    ref = candidate.segment.source
    return (
        int(candidate.priority),
        -candidate.relevance_micros,
        ref.document_id,
        ref.revision_id,
        ref.locator,
        ref.sha256,
    )


def select_context(
    candidates: tuple[ContextCandidate, ...],
    request: ContextSelectionRequest,
) -> ContextSelection:
    identities: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        ref = candidate.segment.source
        if ref.workspace_id != request.workspace_id:
            raise ValueError("cross-workspace context candidate")
        identity = (ref.document_id, ref.revision_id, ref.locator, ref.sha256)
        if identity in identities:
            raise ValueError("duplicate context source identity")
        identities.add(identity)

    ordered = tuple(sorted(candidates, key=_candidate_key))
    if not any(item.priority is ContextPriority.EXPLICIT_TARGET for item in ordered):
        raise ValueError("source-grounded context requires EXPLICIT_TARGET")
    required = tuple(
        item
        for item in ordered
        if item.priority in {ContextPriority.EXPLICIT_TARGET, ContextPriority.CONTRARY_EVIDENCE}
    )
    required_tokens = sum(item.estimated_tokens for item in required)
    if required_tokens > request.max_input_tokens:
        missing = next(
            (item.priority.name for item in required if item.priority is ContextPriority.CONTRARY_EVIDENCE),
            ContextPriority.EXPLICIT_TARGET.name,
        )
        raise ContextBudgetExceeded(f"required context cannot fit: {missing}")

    selected = list(required)
    used = required_tokens
    for candidate in ordered:
        if candidate in required:
            continue
        if used + candidate.estimated_tokens <= request.max_input_tokens:
            selected.append(candidate)
            used += candidate.estimated_tokens
    selected.sort(key=_candidate_key)
    segments = tuple(item.segment for item in selected)
    return ContextSelection(segments, tuple(item.source for item in segments), used)


@dataclass(frozen=True, slots=True)
class ModelRouteRequest:
    task_type: str
    risk: int
    reasoning_level: int
    context_tokens: int
    max_latency_seconds: int | None = None
    max_cost_microusd: int | None = None

    def __post_init__(self) -> None:
        if type(self.task_type) is not str or not self.task_type:
            raise ValueError("task_type invalid")
        if any(type(value) is not int or value < 0 for value in (self.risk, self.reasoning_level, self.context_tokens)):
            raise ValueError("model route dimensions invalid")
        for value in (self.max_latency_seconds, self.max_cost_microusd):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("model route ceiling invalid")


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    policy_id: str
    task_types: tuple[str, ...]
    max_risk: int
    reasoning_level: int
    max_context_tokens: int

    def __post_init__(self) -> None:
        if type(self.policy_id) is not str or not self.policy_id:
            raise ValueError("policy_id invalid")
        if type(self.task_types) is not tuple or not self.task_types:
            raise ValueError("task_types invalid")
        if any(type(item) is not str or not item for item in self.task_types):
            raise ValueError("task type invalid")
        if any(
            type(value) is not int or value < 0
            for value in (self.max_risk, self.reasoning_level, self.max_context_tokens)
        ):
            raise ValueError("route policy dimensions invalid")


@dataclass(frozen=True, slots=True)
class ModelRouteDecision:
    profile: AIModelProfile
    policy_id: str
    reason_codes: tuple[str, ...]


class ModelRouter:
    def __init__(self, profiles: tuple[AIModelProfile, ...], policies: tuple[RoutePolicy, ...]):
        self._profiles = {item.profile_id: item for item in profiles}
        if len(self._profiles) != len(profiles):
            raise ValueError("duplicate model profile")
        self._policies = policies
        policy_ids = tuple(item.policy_id for item in policies)
        if len(set(policy_ids)) != len(policy_ids):
            raise ValueError("duplicate route policy")
        if any(item.policy_id not in self._profiles for item in policies):
            raise ValueError("route policy references unknown profile")

    def route(self, request: ModelRouteRequest) -> ModelRouteDecision:
        eligible = []
        for policy in self._policies:
            profile = self._profiles[policy.policy_id]
            if (
                request.task_type in policy.task_types
                and request.risk <= policy.max_risk
                and request.reasoning_level <= policy.reasoning_level
                and request.context_tokens <= policy.max_context_tokens
                and request.context_tokens <= profile.max_input_tokens
                and profile.structured_output_required
                and (
                    request.max_latency_seconds is None
                    or profile.timeout_seconds <= request.max_latency_seconds
                )
                and (
                    request.max_cost_microusd is None
                    or profile.cost_ceiling_microusd <= request.max_cost_microusd
                )
            ):
                eligible.append((profile.cost_ceiling_microusd, profile.profile_id, policy, profile))
        if not eligible:
            raise ValueError("NO_ELIGIBLE_MODEL_PROFILE")
        _, _, policy, profile = min(eligible)
        return ModelRouteDecision(
            profile,
            policy.policy_id,
            ("TASK", "RISK", "REASONING", "CONTEXT", "STRUCTURED_OUTPUT"),
        )


def _thaw(value: object):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def ai_result_cache_key(request: AIRequest, profile: AIModelProfile) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "task_type": request.task_type,
        "provider": profile.provider,
        "profile_id": profile.profile_id,
        "model": profile.model,
        "prompt_template_hash": request.prompt_template_hash,
        "structured_output_schema_hash": request.structured_output_schema_hash,
        "context_manifest_hash": request.context_manifest_hash,
        "egress": {
            "class": request.egress_manifest.egress_class.value,
            "redaction_manifest": list(request.egress_manifest.redaction_manifest),
            "contains_private_data": request.egress_manifest.contains_private_data,
            "explicitly_authorized": request.egress_manifest.explicitly_authorized,
        },
        "model_parameters": _thaw(profile.model_parameters),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AIResultCacheEntry:
    key: str
    workspace_id: str
    source_refs: tuple[SourceRevisionRef, ...]
    result: object

    def __post_init__(self) -> None:
        if type(self.key) is not str or len(self.key) != 64:
            raise ValueError("cache key invalid")
        if type(self.workspace_id) is not str or not self.workspace_id:
            raise ValueError("cache workspace invalid")
        if type(self.source_refs) is not tuple or any(type(item) is not SourceRevisionRef for item in self.source_refs):
            raise TypeError("cache source refs invalid")
        if any(item.workspace_id != self.workspace_id for item in self.source_refs):
            raise ValueError("cache source workspace mismatch")
        object.__setattr__(self, "result", _freeze_cache_result(self.result))

    @classmethod
    def create(cls, request: AIRequest, profile: AIModelProfile, result: object) -> AIResultCacheEntry:
        return cls(
            key=ai_result_cache_key(request, profile),
            workspace_id=request.workspace_id,
            source_refs=request.egress_manifest.source_refs,
            result=result,
        )


class AIResultCache:
    """Optional workspace-scoped local cache; cached output never gains authority."""

    def __init__(self) -> None:
        self._workspace_id: str | None = None
        self._entries: dict[str, AIResultCacheEntry] = {}

    def put(self, entry: AIResultCacheEntry) -> None:
        if type(entry) is not AIResultCacheEntry:
            raise TypeError("cache entry invalid")
        if self._workspace_id is None:
            self._workspace_id = entry.workspace_id
        if entry.workspace_id != self._workspace_id:
            raise ValueError("cross-workspace cache entry")
        self._entries[entry.key] = entry

    def get(
        self,
        request: AIRequest,
        profile: AIModelProfile,
        current_sources: tuple[SourceRevisionRef, ...],
    ) -> AIResultCacheEntry | None:
        if self._workspace_id is not None and request.workspace_id != self._workspace_id:
            return None
        entry = self._entries.get(ai_result_cache_key(request, profile))
        if entry is None or entry.workspace_id != request.workspace_id:
            return None
        expected_documents = {item.document_id for item in entry.source_refs}
        for document_id in expected_documents:
            expected = {item for item in entry.source_refs if item.document_id == document_id}
            current = {item for item in current_sources if item.document_id == document_id}
            if current != expected:
                return None
        return entry


def _freeze_cache_result(value: object):
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("cache result requires finite JSON numbers")
        return value
    if type(value) in {list, tuple}:
        return tuple(_freeze_cache_result(item) for item in value)
    if type(value) in {dict, MappingProxyType}:
        if any(type(key) is not str for key in value):
            raise TypeError("cache result requires textual keys")
        return MappingProxyType({key: _freeze_cache_result(item) for key, item in value.items()})
    raise TypeError("cache result must be JSON-compatible")

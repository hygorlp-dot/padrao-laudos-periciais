"""Application boundary for local retrieval and exact audited AI context."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from ..ai_context_routing import ContextCandidate, ContextSelectionRequest, estimate_context_tokens, select_context
from ..ai_gateway import AIContextSegment, AIRequest, EgressManifest, SourceRevisionRef, context_manifest_sha256


class LocalContextRetriever(Protocol):
    """Retrieval remains local; this port does not authorize network access."""

    def retrieve(
        self,
        workspace_id: str,
        task_type: str,
        evidence_classes: tuple[str, ...],
    ) -> tuple[ContextCandidate, ...]: ...


class SourceRevisionAuthority(Protocol):
    """Canonical local authority for the current immutable source identity."""

    def is_current(self, ref: SourceRevisionRef) -> bool: ...


@dataclass(frozen=True, slots=True)
class PrivacyProcessedContext:
    workspace_id: str
    segments: tuple[AIContextSegment, ...]
    redaction_manifest: tuple[str, ...]
    contains_private_data: bool

    def __post_init__(self) -> None:
        if type(self.workspace_id) is not str or not self.workspace_id:
            raise ValueError("privacy workspace invalid")
        if type(self.segments) is not tuple or any(type(item) is not AIContextSegment for item in self.segments):
            raise TypeError("privacy segments invalid")
        if type(self.redaction_manifest) is not tuple or any(
            type(item) is not str or not item for item in self.redaction_manifest
        ):
            raise ValueError("privacy redaction manifest invalid")
        if type(self.contains_private_data) is not bool:
            raise TypeError("privacy classification invalid")


class ContextPrivacyAuthority(Protocol):
    def classify_and_redact(
        self,
        workspace_id: str,
        segments: tuple[AIContextSegment, ...],
    ) -> PrivacyProcessedContext: ...


class BuildRoutedAIRequest:
    def __init__(
        self,
        retriever: LocalContextRetriever,
        source_authority: SourceRevisionAuthority,
        privacy_authority: ContextPrivacyAuthority,
    ):
        self._retriever = retriever
        self._source_authority = source_authority
        self._privacy_authority = privacy_authority

    def execute(
        self,
        request: AIRequest,
        *,
        evidence_classes: tuple[str, ...],
        max_input_tokens: int,
    ) -> AIRequest:
        if type(evidence_classes) is not tuple or not evidence_classes:
            raise ValueError("evidence_classes must be a non-empty tuple")
        if any(type(item) is not str or not item.strip() for item in evidence_classes):
            raise ValueError("evidence class invalid")
        required_classes = {"EXPLICIT_TARGET", "CONTRARY_EVIDENCE"}
        missing_classes = required_classes - set(evidence_classes)
        if missing_classes:
            raise ValueError(f"required evidence class missing: {sorted(missing_classes)[0]}")
        candidates = self._retriever.retrieve(request.workspace_id, request.task_type, evidence_classes)
        if type(candidates) is not tuple:
            raise TypeError("local retriever must return a tuple")
        selection = select_context(
            candidates,
            ContextSelectionRequest(request.workspace_id, max_input_tokens),
        )
        if any(not self._source_authority.is_current(ref) for ref in selection.source_refs):
            raise ValueError("selected context does not reference a current source")
        processed = self._privacy_authority.classify_and_redact(request.workspace_id, selection.segments)
        if type(processed) is not PrivacyProcessedContext or processed.workspace_id != request.workspace_id:
            raise ValueError("privacy classification workspace mismatch")
        processed_refs = tuple(segment.source for segment in processed.segments)
        if processed_refs != selection.source_refs:
            raise ValueError("privacy classification changed source identity")
        if sum(estimate_context_tokens(segment.content) for segment in processed.segments) > max_input_tokens:
            raise ValueError("privacy-processed context exceeds token budget")
        egress = request.egress_manifest
        exact_manifest = EgressManifest(
            workspace_id=request.workspace_id,
            egress_class=egress.egress_class,
            source_refs=processed_refs,
            redaction_manifest=processed.redaction_manifest,
            contains_private_data=processed.contains_private_data,
            explicitly_authorized=False,
        )
        return replace(
            request,
            context=processed.segments,
            context_manifest_hash=context_manifest_sha256(processed.segments),
            egress_manifest=exact_manifest,
        )

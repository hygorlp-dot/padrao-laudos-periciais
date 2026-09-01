"""Application boundary for local retrieval and exact audited AI context."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ..ai_context_routing import ContextCandidate, ContextSelectionRequest, select_context
from ..ai_gateway import AIRequest, EgressManifest, SourceRevisionRef, context_manifest_sha256


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


class BuildRoutedAIRequest:
    def __init__(self, retriever: LocalContextRetriever, source_authority: SourceRevisionAuthority):
        self._retriever = retriever
        self._source_authority = source_authority

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
        egress = request.egress_manifest
        exact_manifest = EgressManifest(
            workspace_id=request.workspace_id,
            egress_class=egress.egress_class,
            source_refs=selection.source_refs,
            redaction_manifest=egress.redaction_manifest,
            contains_private_data=egress.contains_private_data,
            explicitly_authorized=egress.explicitly_authorized,
        )
        return replace(
            request,
            context=selection.segments,
            context_manifest_hash=context_manifest_sha256(selection.segments),
            egress_manifest=exact_manifest,
        )

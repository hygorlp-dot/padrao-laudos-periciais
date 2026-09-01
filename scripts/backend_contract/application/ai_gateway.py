"""Boundary de aplicação para executar sugestões de IA sem autoridade canônica."""

from __future__ import annotations

from typing import Protocol

import jsonschema

from ..ai_gateway import (
    AIModelProfile,
    AIProposal,
    AIRequest,
    AIResponse,
    AIRun,
    EgressPolicy,
    SourceRevisionRef,
    UsageRecord,
    context_manifest_payload,
)
from .models import WorkspaceId, thaw_payload
from .ports import ArtifactRevisionRepository, Clock, IdGenerator, WorkspaceRepository


AI_RUN_KIND = "AI_RUN"
AI_PROPOSAL_KIND = "AI_PROPOSAL"


class AIProvider(Protocol):
    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIResponse: ...


class AIProviderFailure(RuntimeError):
    """Falha classificada pelo adapter; detalhes externos nunca cruzam o boundary."""

    def __init__(self, code: str, _private_detail: str | None = None):
        if type(code) is not str or not code.strip():
            raise ValueError("provider failure code inválido")
        self.code = code
        super().__init__(code)


class AIExecutionFailed(RuntimeError):
    """Erro local estável, deliberadamente sem prompt, resposta ou segredo."""


def _source_payload(item: SourceRevisionRef) -> dict[str, object]:
    return {
        "workspace_id": item.workspace_id,
        "document_id": item.document_id,
        "revision_id": item.revision_id,
        "sha256": item.sha256,
        "locator": item.locator,
    }


def _usage_payload(item: UsageRecord | None) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "input_tokens": item.input_tokens,
        "cached_input_tokens": item.cached_input_tokens,
        "output_tokens": item.output_tokens,
        "total_tokens": item.total_tokens,
        "estimated_cost_microusd": item.estimated_cost_microusd,
    }


def _run_payload(item: AIRun) -> dict[str, object]:
    return {
        "run_id": item.run_id,
        "workspace_id": item.workspace_id,
        "task_type": item.task_type,
        "provider": item.provider,
        "model": item.model,
        "model_parameters": thaw_payload(item.model_parameters),
        "prompt_template_version": item.prompt_template_version,
        "prompt_template_hash": item.prompt_template_hash,
        "structured_output_schema_hash": item.structured_output_schema_hash,
        "context_manifest": thaw_payload(item.context_manifest),
        "context_manifest_hash": item.context_manifest_hash,
        "source_refs": [_source_payload(ref) for ref in item.source_refs],
        "egress_class": item.egress_class.value,
        "redaction_manifest": list(item.redaction_manifest),
        "usage": _usage_payload(item.usage),
        "latency_ms": item.latency_ms,
        "provider_response_id": item.provider_response_id,
        "response_hash": item.response_hash,
        "refusal_state": item.refusal_state,
        "error_classification": item.error_classification,
        "proposal_ids": list(item.proposal_ids),
        "created_at": item.created_at,
    }


def _proposal_payload(item: AIProposal) -> dict[str, object]:
    return {
        "proposal_id": item.proposal_id,
        "workspace_id": item.workspace_id,
        "task_type": item.task_type,
        "source_refs": [_source_payload(ref) for ref in item.source_refs],
        "proposal_payload": thaw_payload(item.proposal_payload),
        "provider": item.provider,
        "model": item.model,
        "run_id": item.run_id,
        "created_at": item.created_at,
        "confidence_score": item.confidence_score,
    }


class RunAIProposal:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        revisions: ArtifactRevisionRepository,
        provider: AIProvider,
        egress_policy: EgressPolicy,
        clock: Clock,
        ids: IdGenerator,
    ):
        self._workspaces = workspaces
        self._revisions = revisions
        self._provider = provider
        self._egress_policy = egress_policy
        self._clock = clock
        self._ids = ids

    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIProposal:
        workspace_id = WorkspaceId.parse(request.workspace_id)
        if self._workspaces.get(workspace_id) is None:
            raise AIExecutionFailed("WORKSPACE_NOT_FOUND")
        self._egress_policy.authorize(request)
        run_id = str(self._ids.new_uuid())
        created_at = self._clock.now().isoformat()
        response: AIResponse | None = None
        try:
            response = self._provider.execute(request, profile)
            if response.provider != profile.provider or response.model != profile.model:
                raise AIProviderFailure("PROVIDER_PROFILE_MISMATCH")
            if response.refusal_state != "NONE":
                raise AIProviderFailure("PROVIDER_REFUSAL")
            if response.usage is not None and (
                response.usage.input_tokens > profile.max_input_tokens
                or response.usage.output_tokens > profile.max_output_tokens
            ):
                raise AIProviderFailure("TOKEN_CEILING_EXCEEDED")
            if (
                response.usage is not None
                and response.usage.estimated_cost_microusd is not None
                and response.usage.estimated_cost_microusd > profile.cost_ceiling_microusd
            ):
                raise AIProviderFailure("COST_CEILING_EXCEEDED")
            jsonschema.Draft202012Validator(thaw_payload(request.structured_output_schema)).validate(
                thaw_payload(response.payload)
            )
        except jsonschema.ValidationError:
            self._persist_failed_run(run_id, created_at, request, profile, response, "INVALID_STRUCTURED_OUTPUT")
            raise AIExecutionFailed("INVALID_STRUCTURED_OUTPUT") from None
        except AIProviderFailure as exc:
            self._persist_failed_run(run_id, created_at, request, profile, response, exc.code)
            raise AIExecutionFailed(exc.code) from None
        except Exception:
            self._persist_failed_run(run_id, created_at, request, profile, response, "PROVIDER_UNAVAILABLE")
            raise AIExecutionFailed("PROVIDER_UNAVAILABLE") from None

        proposal_id = str(self._ids.new_uuid())
        proposal = AIProposal(
            proposal_id=proposal_id,
            workspace_id=request.workspace_id,
            task_type=request.task_type,
            source_refs=request.egress_manifest.source_refs,
            proposal_payload=response.payload,
            provider=response.provider,
            model=response.model,
            run_id=run_id,
            created_at=created_at,
            confidence_score=None,
        )
        run = self._run(run_id, created_at, request, profile, response, None, (proposal_id,))
        first = self._append_args(AI_RUN_KIND, run_id, created_at, _run_payload(run))
        second = self._append_args(AI_PROPOSAL_KIND, proposal_id, created_at, _proposal_payload(proposal))
        self._revisions.append_pair_if_latest(
            workspace_id=workspace_id,
            first=first,
            second=second,
            expected_first_revision=None,
            expected_latest=(),
        )
        return proposal

    def _persist_failed_run(
        self,
        run_id: str,
        created_at: str,
        request: AIRequest,
        profile: AIModelProfile,
        response: AIResponse | None,
        code: str,
    ) -> None:
        run = self._run(run_id, created_at, request, profile, response, code, ())
        self._revisions.append(
            workspace_id=WorkspaceId.parse(request.workspace_id),
            **self._append_args(AI_RUN_KIND, run_id, created_at, _run_payload(run)),
        )

    def _run(
        self,
        run_id: str,
        created_at: str,
        request: AIRequest,
        profile: AIModelProfile,
        response: AIResponse | None,
        error: str | None,
        proposal_ids: tuple[str, ...],
    ) -> AIRun:
        return AIRun(
            run_id=run_id,
            workspace_id=request.workspace_id,
            task_type=request.task_type,
            provider=response.provider if response is not None else profile.provider,
            model=response.model if response is not None else profile.model,
            model_parameters=profile.model_parameters,
            prompt_template_version=request.prompt_template_version,
            prompt_template_hash=request.prompt_template_hash,
            structured_output_schema_hash=request.structured_output_schema_hash,
            context_manifest=context_manifest_payload(request.context),
            context_manifest_hash=request.context_manifest_hash,
            source_refs=request.egress_manifest.source_refs,
            egress_class=request.egress_manifest.egress_class,
            redaction_manifest=request.egress_manifest.redaction_manifest,
            usage=response.usage if response is not None else None,
            latency_ms=response.latency_ms if response is not None else 0,
            provider_response_id=response.provider_response_id if response is not None else None,
            response_hash=response.response_hash if response is not None else None,
            refusal_state=response.refusal_state if response is not None else "UNKNOWN",
            error_classification=error,
            proposal_ids=proposal_ids,
            created_at=created_at,
        )

    def _append_args(self, kind: str, artifact_id: str, created_at: str, payload: object) -> dict[str, object]:
        return {
            "artifact_kind": kind,
            "artifact_id": artifact_id,
            "revision_id": str(self._ids.new_uuid()),
            "created_at": created_at,
            "payload": payload,
        }

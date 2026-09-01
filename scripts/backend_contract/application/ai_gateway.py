"""Boundary de aplicação para executar sugestões de IA sem autoridade canônica."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Protocol

import jsonschema

from ..ai_gateway import (
    AIModelProfile,
    AIProposal,
    AIRequest,
    AIResponse,
    AIRun,
    EgressClass,
    EgressDenied,
    EgressPolicy,
    SourceRevisionRef,
    UsageRecord,
    context_manifest_payload,
    response_payload_sha256,
)
from .models import WorkspaceId, thaw_payload
from .ports import ArtifactRevisionRepository, Clock, IdGenerator, WorkspaceRepository


AI_RUN_KIND = "AI_RUN"
AI_PROPOSAL_KIND = "AI_PROPOSAL"
AI_EVAL_OBSERVATION_KIND = "AI_EVAL_OBSERVATION"
AI_EVAL_REPORT_KIND = "AI_EVAL_REPORT"


class AIProvider(Protocol):
    is_remote: bool

    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIResponse: ...


class AICostAuthorizer(Protocol):
    def authorize_and_reserve(
        self, workspace_id: str, session_id: str, *, input_tokens: int,
        output_tokens: int, estimated_cost_microusd: int,
    ) -> object: ...


class AIProviderFailure(RuntimeError):
    """Falha classificada pelo adapter; detalhes externos nunca cruzam o boundary."""

    def __init__(self, code: str, _private_detail: str | None = None, *, latency_ms: int = 0):
        if type(code) is not str or not code.strip():
            raise ValueError("provider failure code inválido")
        if type(latency_ms) is not int or latency_ms < 0:
            raise ValueError("provider failure latency invalid")
        self.code = code
        self.latency_ms = latency_ms
        super().__init__(code)


class AIExecutionFailed(RuntimeError):
    def __init__(self, code: str, run: AIRun | None = None):
        self.run = run
        super().__init__(code)

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
        "profile_id": item.profile_id,
        "cache_hit": item.cache_hit,
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


def _eval_payload(item) -> dict[str, object]:
    return {
        field: _plain_payload(getattr(item, field))
        for field in item.__dataclass_fields__
        if field != "_derivation_token"
    }


def _plain_payload(value):
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, SourceRevisionRef):
        return _source_payload(value)
    if isinstance(value, dict):
        return {key: _plain_payload(item) for key, item in value.items()}
    try:
        thawed = thaw_payload(value)
    except TypeError:
        thawed = value
    if isinstance(thawed, dict):
        return {key: _plain_payload(item) for key, item in thawed.items()}
    if isinstance(thawed, (list, tuple)):
        return [_plain_payload(item) for item in thawed]
    return thawed


class RunAIProposal:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        revisions: ArtifactRevisionRepository,
        provider: AIProvider,
        egress_policy: EgressPolicy,
        clock: Clock,
        ids: IdGenerator,
        cost_ledger: AICostAuthorizer,
        cost_session_id: str = "DEFAULT_AI_SESSION",
    ):
        self._workspaces = workspaces
        self._revisions = revisions
        self._provider = provider
        self._egress_policy = egress_policy
        self._clock = clock
        self._ids = ids
        if not callable(getattr(cost_ledger, "authorize_and_reserve", None)):
            raise TypeError("AI cost ledger required")
        self._cost_ledger = cost_ledger
        if type(cost_session_id) is not str or not cost_session_id.strip():
            raise ValueError("AI cost session identity invalid")
        self._cost_session_id = cost_session_id

    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIProposal:
        proposal, _run = self.execute_with_run(request, profile)
        return proposal

    def execute_with_run(self, request: AIRequest, profile: AIModelProfile) -> tuple[AIProposal, AIRun]:
        workspace_id = WorkspaceId.parse(request.workspace_id)
        if self._workspaces.get(workspace_id) is None:
            raise AIExecutionFailed("WORKSPACE_NOT_FOUND")
        self._egress_policy.authorize(request)
        if request.egress_manifest.egress_class is EgressClass.LOCAL_ONLY and self._provider.is_remote:
            raise EgressDenied("LOCAL_ONLY_PROVIDER_MISMATCH")
        try:
            self._cost_ledger.authorize_and_reserve(
                    request.workspace_id,
                    self._cost_session_id,
                    input_tokens=sum(
                        (len(segment.content.encode("utf-8")) + 3) // 4
                        for segment in request.context
                    ),
                    output_tokens=profile.max_output_tokens,
                    estimated_cost_microusd=profile.cost_ceiling_microusd,
            )
        except ValueError as exc:
            raise AIExecutionFailed("COST_OR_TOKEN_BUDGET_EXCEEDED") from exc
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
            if response_payload_sha256(response.payload) != response.response_hash:
                raise AIProviderFailure("INVALID_RESPONSE_HASH")
        except jsonschema.ValidationError:
            run = self._persist_failed_run(run_id, created_at, request, profile, response, "INVALID_STRUCTURED_OUTPUT")
            raise AIExecutionFailed("INVALID_STRUCTURED_OUTPUT", run) from None
        except AIProviderFailure as exc:
            run = self._persist_failed_run(run_id, created_at, request, profile, response, exc.code, exc.latency_ms)
            raise AIExecutionFailed(exc.code, run) from None
        except Exception:
            run = self._persist_failed_run(run_id, created_at, request, profile, response, "PROVIDER_UNAVAILABLE")
            raise AIExecutionFailed("PROVIDER_UNAVAILABLE", run) from None

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
        return proposal, run

    def verify_persisted(self, run: AIRun, proposal: AIProposal | None = None) -> None:
        workspace_id = WorkspaceId.parse(run.workspace_id)
        persisted_run = self._revisions.latest(workspace_id, AI_RUN_KIND, run.run_id)
        if persisted_run is None or _plain_payload(persisted_run.payload) != _plain_payload(_run_payload(run)):
            raise AIExecutionFailed("AI_RUN_PERSISTENCE_MISMATCH")
        if proposal is not None:
            persisted_proposal = self._revisions.latest(
                workspace_id, AI_PROPOSAL_KIND, proposal.proposal_id
            )
            if (
                proposal.run_id != run.run_id
                or persisted_proposal is None
                or _plain_payload(persisted_proposal.payload) != _plain_payload(_proposal_payload(proposal))
            ):
                raise AIExecutionFailed("AI_PROPOSAL_PERSISTENCE_MISMATCH")

    def observe_persisted_domain_proposal(
        self, dataset, case, raw_proposal, run, domain_proposal, telemetry, human_outcome
    ):
        from ..ai_eval_productization import observe_domain_proposal

        self.verify_persisted(run, raw_proposal)
        observation = observe_domain_proposal(
            dataset.version, dataset.sha256, case, domain_proposal, run, telemetry, human_outcome
        )
        self._persist_eval_observation(observation, run.created_at)
        return observation

    def observe_persisted_failed_run(self, dataset, case, run):
        from ..ai_eval_productization import observe_failed_run

        self.verify_persisted(run)
        observation = observe_failed_run(dataset.version, dataset.sha256, case, run)
        self._persist_eval_observation(observation, run.created_at)
        return observation

    def evaluate_persisted_dataset(self, dataset, observations):
        from ..ai_eval_productization import evaluate_ai_dataset

        for observation in observations:
            persisted = self._revisions.latest(
                WorkspaceId.parse(observation.workspace_id),
                AI_EVAL_OBSERVATION_KIND,
                observation.attestation_sha256,
            )
            if persisted is None or _plain_payload(persisted.payload) != _plain_payload(
                _eval_payload(observation)
            ):
                raise AIExecutionFailed("AI_EVAL_OBSERVATION_PERSISTENCE_MISMATCH")
        report = evaluate_ai_dataset(dataset, observations)
        if report.observation_attestations != tuple(
            next(item.attestation_sha256 for item in observations if item.case_id == case.case_id)
            for case in dataset.cases
        ):
            raise AIExecutionFailed("AI_EVAL_REPORT_MANIFEST_MISMATCH")
        report_payload = _eval_payload(report)
        report_id = hashlib.sha256(
            json.dumps(report_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        created_at = self._clock.now().isoformat()
        workspace_ids = {item.workspace_id for item in observations}
        if len(workspace_ids) != 1:
            raise AIExecutionFailed("AI_EVAL_REPORT_WORKSPACE_MISMATCH")
        workspace_id = WorkspaceId.parse(next(iter(workspace_ids)))
        self._revisions.append_if_latest(
            workspace_id=workspace_id,
            **self._append_args(AI_EVAL_REPORT_KIND, report_id, created_at, report_payload),
            expected_revision=None,
        )
        persisted = self._revisions.latest(workspace_id, AI_EVAL_REPORT_KIND, report_id)
        if persisted is None or _plain_payload(persisted.payload) != _plain_payload(report_payload):
            raise AIExecutionFailed("AI_EVAL_REPORT_PERSISTENCE_MISMATCH")
        return report

    def load_persisted_eval_observation(self, workspace_id: str, attestation_sha256: str):
        from ..ai_eval_productization import ai_eval_observation_from_mapping

        record = self._revisions.latest(
            WorkspaceId.parse(workspace_id), AI_EVAL_OBSERVATION_KIND, attestation_sha256
        )
        if record is None:
            raise AIExecutionFailed("AI_EVAL_OBSERVATION_NOT_FOUND")
        try:
            observation = ai_eval_observation_from_mapping(_plain_payload(record.payload))
        except (TypeError, ValueError) as exc:
            raise AIExecutionFailed("AI_EVAL_OBSERVATION_PERSISTENCE_MISMATCH") from exc
        if observation.workspace_id != workspace_id or observation.attestation_sha256 != attestation_sha256:
            raise AIExecutionFailed("AI_EVAL_OBSERVATION_PERSISTENCE_MISMATCH")
        return observation

    def load_persisted_eval_report(self, workspace_id: str, report_id: str):
        from ..ai_eval_productization import ai_eval_report_from_mapping

        record = self._revisions.latest(
            WorkspaceId.parse(workspace_id), AI_EVAL_REPORT_KIND, report_id
        )
        if record is None:
            raise AIExecutionFailed("AI_EVAL_REPORT_NOT_FOUND")
        payload = _plain_payload(record.payload)
        calculated = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if calculated != report_id:
            raise AIExecutionFailed("AI_EVAL_REPORT_PERSISTENCE_MISMATCH")
        try:
            return ai_eval_report_from_mapping(payload)
        except (TypeError, ValueError) as exc:
            raise AIExecutionFailed("AI_EVAL_REPORT_PERSISTENCE_MISMATCH") from exc

    def _persist_eval_observation(self, observation, created_at: str) -> None:
        workspace_id = WorkspaceId.parse(observation.workspace_id)
        payload = _eval_payload(observation)
        self._revisions.append_if_latest(
            workspace_id=workspace_id,
            **self._append_args(
                AI_EVAL_OBSERVATION_KIND,
                observation.attestation_sha256,
                created_at,
                payload,
            ),
            expected_revision=None,
        )
        persisted = self._revisions.latest(
            workspace_id, AI_EVAL_OBSERVATION_KIND, observation.attestation_sha256
        )
        if persisted is None or _plain_payload(persisted.payload) != _plain_payload(payload):
            raise AIExecutionFailed("AI_EVAL_OBSERVATION_PERSISTENCE_MISMATCH")

    def _persist_failed_run(
        self,
        run_id: str,
        created_at: str,
        request: AIRequest,
        profile: AIModelProfile,
        response: AIResponse | None,
        code: str,
        latency_ms: int = 0,
    ) -> AIRun:
        run = self._run(run_id, created_at, request, profile, response, code, (), latency_ms)
        self._revisions.append_if_latest(
            workspace_id=WorkspaceId.parse(request.workspace_id),
            **self._append_args(AI_RUN_KIND, run_id, created_at, _run_payload(run)),
            expected_revision=None,
        )
        return run

    def _run(
        self,
        run_id: str,
        created_at: str,
        request: AIRequest,
        profile: AIModelProfile,
        response: AIResponse | None,
        error: str | None,
        proposal_ids: tuple[str, ...],
        failure_latency_ms: int = 0,
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
            latency_ms=response.latency_ms if response is not None else failure_latency_ms,
            provider_response_id=response.provider_response_id if response is not None else None,
            response_hash=response.response_hash if response is not None else None,
            refusal_state=response.refusal_state if response is not None else "UNKNOWN",
            error_classification=error,
            proposal_ids=proposal_ids,
            created_at=created_at,
            profile_id=profile.profile_id,
            cache_hit=False,
        )

    def _append_args(self, kind: str, artifact_id: str, created_at: str, payload: object) -> dict[str, object]:
        return {
            "artifact_kind": kind,
            "artifact_id": artifact_id,
            "revision_id": str(self._ids.new_uuid()),
            "created_at": created_at,
            "payload": payload,
        }

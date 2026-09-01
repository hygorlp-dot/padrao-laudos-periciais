from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType
from uuid import UUID

import pytest

from scripts.backend_contract.ai_gateway import (
    AIContextSegment,
    AIModelProfile,
    AIProposal,
    AIRequest,
    AIRun,
    EgressClass,
    EgressDenied,
    EgressManifest,
    EgressPolicy,
    SourceRevisionRef,
    UsageRecord,
)


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
SHA256 = "a" * 64
SCHEMA_SHA256 = "b" * 64
PROMPT_SHA256 = "c" * 64
CONTEXT_SHA256 = "d" * 64


def source_ref(*, workspace_id: str = WORKSPACE_ID) -> SourceRevisionRef:
    return SourceRevisionRef(
        workspace_id=workspace_id,
        document_id="document-1",
        revision_id="revision-1",
        sha256=SHA256,
        locator="page=1;segment=2",
    )


def manifest(
    *,
    egress_class: EgressClass = EgressClass.REMOTE_SANITIZED,
    contains_private_data: bool = False,
    explicitly_authorized: bool = False,
) -> EgressManifest:
    return EgressManifest(
        workspace_id=WORKSPACE_ID,
        egress_class=egress_class,
        source_refs=(source_ref(),),
        redaction_manifest=("cpf",) if egress_class is EgressClass.REMOTE_SANITIZED else (),
        contains_private_data=contains_private_data,
        explicitly_authorized=explicitly_authorized,
    )


def request(*, egress_manifest: EgressManifest | None = None) -> AIRequest:
    return AIRequest(
        workspace_id=WORKSPACE_ID,
        task_type="CASE_ANALYSIS_PROPOSAL",
        prompt_template_version="case-analysis-v1",
        prompt_template_hash=PROMPT_SHA256,
        structured_output_schema={
            "type": "object",
            "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
            "required": ["claims"],
            "additionalProperties": False,
        },
        structured_output_schema_hash=SCHEMA_SHA256,
        context=(AIContextSegment(source=source_ref(), content="Trecho sintético."),),
        context_manifest_hash=CONTEXT_SHA256,
        egress_manifest=egress_manifest or manifest(),
    )


def test_remote_egress_is_denied_by_default() -> None:
    with pytest.raises(EgressDenied, match="REMOTE_AI_EGRESS_DENIED"):
        EgressPolicy().authorize(request())


def test_remote_sanitized_requires_policy_enablement_and_exact_manifest() -> None:
    policy = EgressPolicy(remote_sanitized_enabled=True)

    assert policy.authorize(request()) is None

    mismatched = manifest()
    foreign_request = replace(
        request(),
        context=(AIContextSegment(source=source_ref(workspace_id=OTHER_WORKSPACE_ID), content="x"),),
        egress_manifest=mismatched,
    )
    with pytest.raises(ValueError, match="workspace"):
        policy.authorize(foreign_request)


def test_private_remote_egress_requires_separate_explicit_authority() -> None:
    policy = EgressPolicy(remote_sanitized_enabled=True, remote_private_enabled=True)
    denied_manifest = manifest(
        egress_class=EgressClass.REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED,
        contains_private_data=True,
        explicitly_authorized=False,
    )

    with pytest.raises(EgressDenied, match="PRIVATE_EGRESS_NOT_AUTHORIZED"):
        policy.authorize(request(egress_manifest=denied_manifest))

    allowed_manifest = manifest(
        egress_class=EgressClass.REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED,
        contains_private_data=True,
        explicitly_authorized=True,
    )
    assert policy.authorize(request(egress_manifest=allowed_manifest)) is None


def test_contracts_validate_hashes_ids_and_are_deeply_immutable() -> None:
    item = request()
    assert isinstance(item.structured_output_schema, MappingProxyType)
    with pytest.raises(TypeError):
        item.structured_output_schema["type"] = "array"
    with pytest.raises(FrozenInstanceError):
        item.task_type = "REPORT_APPROVAL"
    with pytest.raises(ValueError, match="sha256"):
        SourceRevisionRef(
            workspace_id=WORKSPACE_ID,
            document_id="document-1",
            revision_id="revision-1",
            sha256="forged",
            locator="page=1",
        )
    with pytest.raises(ValueError, match="UUID"):
        EgressManifest(
            workspace_id="not-a-uuid",
            egress_class=EgressClass.LOCAL_ONLY,
            source_refs=(),
            redaction_manifest=(),
            contains_private_data=False,
            explicitly_authorized=False,
        )


def test_model_profile_and_usage_have_explicit_cost_and_token_limits() -> None:
    profile = AIModelProfile(
        profile_id="FAST_EXTRACTION",
        provider="OPENAI",
        model="configured-model",
        max_input_tokens=4_000,
        max_output_tokens=800,
        cost_ceiling_microusd=25_000,
        timeout_seconds=30.0,
        structured_output_required=True,
        model_parameters={"temperature": 0},
    )
    usage = UsageRecord(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=30,
        total_tokens=130,
        estimated_cost_microusd=500,
    )

    assert profile.model == "configured-model"
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens
    with pytest.raises(ValueError, match="total_tokens"):
        UsageRecord(100, 20, 30, 999, 500)


def test_ai_proposal_and_run_ids_are_canonical_and_carry_no_authority_field() -> None:
    proposal = AIProposal(
        proposal_id="33333333-3333-4333-8333-333333333333",
        workspace_id=WORKSPACE_ID,
        task_type="CASE_ANALYSIS_PROPOSAL",
        source_refs=(source_ref(),),
        proposal_payload={"claims": ["Alegação sintética"]},
        provider="OPENAI",
        model="configured-model",
        run_id="44444444-4444-4444-8444-444444444444",
        created_at="2026-09-01T12:00:00+00:00",
        confidence_score=0.7,
    )
    run = AIRun(
        run_id=proposal.run_id,
        workspace_id=WORKSPACE_ID,
        task_type=proposal.task_type,
        provider="OPENAI",
        model="configured-model",
        model_parameters={"temperature": 0},
        prompt_template_version="case-analysis-v1",
        prompt_template_hash=PROMPT_SHA256,
        structured_output_schema_hash=SCHEMA_SHA256,
        context_manifest_hash=CONTEXT_SHA256,
        source_refs=(source_ref(),),
        egress_class=EgressClass.REMOTE_SANITIZED,
        redaction_manifest=("cpf",),
        usage=UsageRecord(100, 20, 30, 130, 500),
        latency_ms=25,
        provider_response_id="response-1",
        response_hash=SHA256,
        refusal_state="NONE",
        error_classification=None,
        proposal_ids=(proposal.proposal_id,),
        created_at=proposal.created_at,
    )

    assert UUID(proposal.proposal_id).version == 4
    assert UUID(run.run_id).version == 4
    assert not hasattr(proposal, "approved")
    assert not hasattr(proposal, "effective")
    assert not hasattr(run, "professional_decision")


@pytest.mark.parametrize("secret_field", ["api_key", "secret", "authorization", "bearer_token"])
def test_ai_payload_rejects_secret_shaped_fields(secret_field: str) -> None:
    with pytest.raises(ValueError, match="secret"):
        AIProposal(
            proposal_id="33333333-3333-4333-8333-333333333333",
            workspace_id=WORKSPACE_ID,
            task_type="CASE_ANALYSIS_PROPOSAL",
            source_refs=(source_ref(),),
            proposal_payload={secret_field: "must-not-persist"},
            provider="OPENAI",
            model="configured-model",
            run_id="44444444-4444-4444-8444-444444444444",
            created_at="2026-09-01T12:00:00+00:00",
            confidence_score=None,
        )

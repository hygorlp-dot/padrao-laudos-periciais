from __future__ import annotations

from dataclasses import replace

import jsonschema
import pytest

from scripts.backend_contract.ai_domain_proposals import (
    DomainAIProposal,
    DomainProposalItem,
    DomainProposalKind,
    ReportAuthorityContext,
    domain_proposal_schema,
    validate_domain_proposal,
)
from scripts.backend_contract.ai_gateway import AIProposal, SourceRevisionRef
from scripts.backend_contract.ai_gateway import structured_output_schema_sha256
from scripts.backend_contract.application.ai_domain_proposals import RunDomainAIProposal
from scripts.backend_contract.application.models import thaw_payload
from tests.test_ai_context_routing_v1 import profile
from tests.test_ai_gateway_core_v1 import request


WORKSPACE = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def source(*, workspace: str = WORKSPACE, revision: str = "revision-1") -> SourceRevisionRef:
    return SourceRevisionRef(
        workspace_id=workspace,
        document_id="document-1",
        revision_id=revision,
        sha256="a" * 64,
        locator="page=1;segment=2",
    )


def source_payload(ref: SourceRevisionRef) -> dict[str, str]:
    return {
        "workspace_id": ref.workspace_id,
        "document_id": ref.document_id,
        "revision_id": ref.revision_id,
        "sha256": ref.sha256,
        "locator": ref.locator,
    }


def proposal(kind: DomainProposalKind, item_type: str, *, ref: SourceRevisionRef | None = None) -> AIProposal:
    ref = ref or source()
    return AIProposal(
        proposal_id="11111111-1111-4111-8111-111111111112",
        workspace_id=WORKSPACE,
        task_type=kind.value,
        source_refs=(ref,),
        proposal_payload={
            "items": [
                {
                    "item_type": item_type,
                    "content": "Synthetic source-grounded proposal.",
                    "source_refs": [source_payload(ref)],
                }
            ]
        },
        provider="OPENAI",
        model="model-fast",
        run_id="11111111-1111-4111-8111-111111111113",
        created_at="2026-09-01T12:00:00+00:00",
        confidence_score=None,
    )


@pytest.mark.parametrize(
    ("kind", "item_type"),
    (
        (DomainProposalKind.CASE_ANALYSIS, "CLAIM"),
        (DomainProposalKind.PLANNING, "INSPECTION_REQUIREMENT"),
        (DomainProposalKind.EVIDENCE_TECHNICAL, "CONTRARY_EVIDENCE_CANDIDATE"),
        (DomainProposalKind.REPORT_DRAFT, "REPORT_SECTION_DRAFT"),
    ),
)
def test_domain_proposal_schemas_are_strict_and_validate_allowed_items(kind, item_type) -> None:
    candidate = proposal(kind, item_type)
    schema = domain_proposal_schema(kind)

    jsonschema.Draft202012Validator(schema).validate(thaw_payload(candidate.proposal_payload))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["items"]["items"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("kind", "item_type"),
    (
        (DomainProposalKind.CASE_ANALYSIS, "CONFLICT_CANDIDATE"),
        (DomainProposalKind.PLANNING, "MEASUREMENT_CANDIDATE"),
        (DomainProposalKind.EVIDENCE_TECHNICAL, "FINDING_PROPOSITION"),
    ),
)
def test_validated_domain_output_remains_source_grounded_proposal_only(kind, item_type) -> None:
    validated = validate_domain_proposal(proposal(kind, item_type), kind)

    assert validated.authority == "PROPOSAL_ONLY"
    assert validated.kind is kind
    assert validated.items[0].source_refs == (source(),)
    assert validated.items[0].content == "Synthetic source-grounded proposal."
    with pytest.raises(ValueError, match="proposal-only"):
        replace(validated, authority="APPROVED")


def test_public_domain_value_objects_reject_ungrounded_or_cross_workspace_forgery() -> None:
    with pytest.raises(ValueError, match="source-grounded"):
        DomainProposalItem("CLAIM", "Synthetic", ())
    foreign_item = DomainProposalItem("CLAIM", "Synthetic", (source(workspace=OTHER),))
    with pytest.raises(ValueError, match="workspace"):
        DomainAIProposal(
            "11111111-1111-4111-8111-111111111112",
            WORKSPACE,
            "11111111-1111-4111-8111-111111111113",
            DomainProposalKind.CASE_ANALYSIS,
            (foreign_item,),
        )


def test_public_domain_value_object_enforces_kind_and_report_authority() -> None:
    claim = DomainProposalItem("CLAIM", "Synthetic", (source(),))
    report_item = DomainProposalItem("REPORT_SECTION_DRAFT", "Synthetic", (source(),))
    base = (
        "11111111-1111-4111-8111-111111111112",
        WORKSPACE,
        "11111111-1111-4111-8111-111111111113",
        DomainProposalKind.REPORT_DRAFT,
    )
    with pytest.raises(ValueError, match="incompatible"):
        DomainAIProposal(*base, (claim,), report_authority=report_authority())
    with pytest.raises(ValueError, match="upstream authority"):
        DomainAIProposal(*base, (report_item,))


def test_unknown_unsourced_and_cross_workspace_refs_fail_closed() -> None:
    base = proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM")
    payload = thaw_payload(base.proposal_payload)
    payload["items"][0]["source_refs"] = []
    with pytest.raises(ValueError, match="source-grounded"):
        validate_domain_proposal(replace(base, proposal_payload=payload), DomainProposalKind.CASE_ANALYSIS)

    payload["items"][0]["source_refs"] = [source_payload(source(revision="unknown"))]
    with pytest.raises(ValueError, match="unknown source"):
        validate_domain_proposal(replace(base, proposal_payload=payload), DomainProposalKind.CASE_ANALYSIS)

    foreign = source(workspace=OTHER)
    payload["items"][0]["source_refs"] = [source_payload(foreign)]
    with pytest.raises(ValueError, match="workspace"):
        validate_domain_proposal(replace(base, proposal_payload=payload), DomainProposalKind.CASE_ANALYSIS)


@pytest.mark.parametrize(
    "forbidden",
    ("approved", "effective", "human_review_decision", "professional_decision", "finalized"),
)
def test_authority_claims_are_rejected_recursively(forbidden: str) -> None:
    base = proposal(DomainProposalKind.TECHNICAL_FINDING, "FINDING_PROPOSITION")
    payload = thaw_payload(base.proposal_payload)
    payload["items"][0][forbidden] = True
    with pytest.raises(ValueError, match="authority field"):
        validate_domain_proposal(replace(base, proposal_payload=payload), DomainProposalKind.TECHNICAL_FINDING)


def test_task_kind_mismatch_and_empty_material_output_fail_closed() -> None:
    base = proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM")
    with pytest.raises(ValueError, match="task type"):
        validate_domain_proposal(base, DomainProposalKind.PLANNING)
    with pytest.raises(ValueError, match="material proposal"):
        validate_domain_proposal(
            replace(base, proposal_payload={"items": []}),
            DomainProposalKind.CASE_ANALYSIS,
        )


def report_authority(**changes) -> ReportAuthorityContext:
    values = {
        "workspace_id": WORKSPACE,
        "case_analysis_reviewed": True,
        "planning_professionally_reviewed_or_not_applicable": True,
        "technical_findings_effective": True,
        "professional_decisions_present": True,
        "canonical_question_links_present": True,
    }
    values.update(changes)
    return ReportAuthorityContext(**values)


def test_report_draft_requires_all_authoritative_upstream_state_and_remains_unapproved() -> None:
    draft = proposal(DomainProposalKind.REPORT_DRAFT, "REPORT_SECTION_DRAFT")
    validated = validate_domain_proposal(draft, DomainProposalKind.REPORT_DRAFT, report_authority=report_authority())
    assert validated.authority == "PROPOSAL_ONLY"

    fields = tuple(field for field in report_authority().__dataclass_fields__ if field != "workspace_id")
    for field in fields:
        with pytest.raises(ValueError, match="report upstream authority"):
            validate_domain_proposal(
                draft,
                DomainProposalKind.REPORT_DRAFT,
                report_authority=report_authority(**{field: False}),
            )
    with pytest.raises(ValueError, match="report upstream authority"):
        validate_domain_proposal(draft, DomainProposalKind.REPORT_DRAFT)


class Runner:
    def __init__(self, result: AIProposal):
        self.result = result
        self.calls = []

    def execute(self, ai_request, model_profile):
        self.calls.append((ai_request, model_profile))
        return self.result


class ReportAuthorityReader:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get(self, workspace_id: str):
        self.calls.append(workspace_id)
        return self.value


def domain_request(kind: DomainProposalKind):
    base = request()
    schema = domain_proposal_schema(kind, allowed_source_refs=base.egress_manifest.source_refs)
    return replace(
        base,
        task_type=kind.value,
        structured_output_schema=schema,
        structured_output_schema_hash=structured_output_schema_sha256(schema),
    )


def test_application_requires_exact_source_bound_schema_before_runner_persistence() -> None:
    kind = DomainProposalKind.CASE_ANALYSIS
    runner = Runner(proposal(kind, "CLAIM"))
    service = RunDomainAIProposal(runner)

    validated = service.execute(domain_request(kind), profile("FAST", 1_000), kind)
    assert validated.authority == "PROPOSAL_ONLY"
    assert len(runner.calls) == 1
    with pytest.raises(ValueError, match="source-bound domain schema"):
        service.execute(
            replace(
                domain_request(kind),
                structured_output_schema=request().structured_output_schema,
                structured_output_schema_hash=request().structured_output_schema_hash,
            ),
            profile("FAST", 1_000),
            kind,
        )
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "result",
    (
        proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM", ref=source(revision="forged")),
        replace(
            proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM", ref=source(workspace=OTHER)),
            workspace_id=OTHER,
        ),
        replace(proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM"), provider="OTHER"),
        replace(proposal(DomainProposalKind.CASE_ANALYSIS, "CLAIM"), model="other-model"),
    ),
)
def test_application_rejects_runner_result_not_bound_to_request_and_profile(result) -> None:
    kind = DomainProposalKind.CASE_ANALYSIS
    with pytest.raises(ValueError, match="runner result"):
        RunDomainAIProposal(Runner(result)).execute(domain_request(kind), profile("FAST", 1_000), kind)

def test_application_blocks_report_before_provider_when_upstream_is_not_authorized() -> None:
    kind = DomainProposalKind.REPORT_DRAFT
    runner = Runner(proposal(kind, "REPORT_SECTION_DRAFT"))
    authority = ReportAuthorityReader(report_authority(technical_findings_effective=False))

    with pytest.raises(ValueError, match="report upstream authority"):
        RunDomainAIProposal(runner, authority).execute(domain_request(kind), profile("FAST", 1_000), kind)
    assert runner.calls == []
    assert authority.calls == [WORKSPACE]

    foreign = ReportAuthorityReader(report_authority(workspace_id=OTHER))
    with pytest.raises(ValueError, match="report upstream authority"):
        RunDomainAIProposal(runner, foreign).execute(domain_request(kind), profile("FAST", 1_000), kind)
    assert runner.calls == []

from pathlib import Path

from scripts.backend_contract.ai_context_routing import (
    ContextCandidate,
    ContextPriority,
    ContextSelectionRequest,
    estimate_context_tokens,
    select_context,
)
from scripts.backend_contract.ai_domain_proposals import (
    DomainAIProposal,
    DomainProposalItem,
    DomainProposalKind,
)
from scripts.backend_contract.ai_eval_productization import (
    AIEvalScenario,
    AIEvalTelemetry,
    HumanEvalOutcome,
    evaluate_ai_dataset,
    load_ai_eval_dataset,
    observe_domain_proposal,
)
from scripts.backend_contract.ai_gateway import AIContextSegment, SourceRevisionRef


DATASET = Path(__file__).parent / "fixtures" / "ai-eval-dataset-v1.json"

ITEM_TYPES = {
    DomainProposalKind.CASE_ANALYSIS: "CLAIM",
    DomainProposalKind.PLANNING: "RISK_GAP_CANDIDATE",
    DomainProposalKind.EVIDENCE_TECHNICAL: "CONTRARY_EVIDENCE_CANDIDATE",
    DomainProposalKind.TECHNICAL_FINDING: "UNCERTAINTY_DESCRIPTION",
}


def test_stage10_longitudinal_synthetic_oracle_preserves_grounding_authority_and_isolation() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    observations = []

    for ordinal, case in enumerate(dataset.cases, start=1):
        candidates = []
        for source_ordinal, document_id in enumerate(case.expected_source_ids):
            source = SourceRevisionRef(
                case.workspace_id,
                document_id,
                "reviewed-revision-1",
                f"{ordinal:x}"[-1] * 64,
                f"synthetic-case={case.case_id};source={source_ordinal}",
            )
            content = f"Synthetic reviewed evidence for {case.scenario.value}: {document_id}"
            priority = (
                ContextPriority.CONTRARY_EVIDENCE
                if case.scenario is AIEvalScenario.CONTRARY_EVIDENCE and source_ordinal == 1
                else ContextPriority.EXPLICIT_TARGET
            )
            candidates.append(
                ContextCandidate(
                    AIContextSegment(source, content),
                    priority,
                    estimate_context_tokens(content),
                    1_000_000 - source_ordinal,
                )
            )

        selection = select_context(
            tuple(reversed(candidates)),
            ContextSelectionRequest(case.workspace_id, 1_000),
        )
        kind = DomainProposalKind(case.task_type)
        proposal = DomainAIProposal(
            f"00000000-0000-4000-8000-{ordinal:012d}",
            case.workspace_id,
            f"10000000-0000-4000-8000-{ordinal:012d}",
            kind,
            (
                DomainProposalItem(
                    ITEM_TYPES[kind],
                    "Synthetic proposal requiring professional review.",
                    selection.source_refs,
                ),
            ),
        )
        telemetry = AIEvalTelemetry(
            "SYNTHETIC_LOCAL",
            "EVAL_PROFILE_V1",
            "synthetic-model-v1",
            "prompt-v1",
            "a" * 64,
            "b" * 64,
            selection.total_estimated_tokens,
            0,
            20,
            100,
            25,
            False,
        )
        outcome = (
            HumanEvalOutcome.REJECTED
            if case.scenario is AIEvalScenario.REJECTED_HUMAN_REVIEW
            else HumanEvalOutcome.ACCEPTED
        )
        observations.append(observe_domain_proposal(dataset.version, case, proposal, telemetry, outcome))

    report = evaluate_ai_dataset(dataset, tuple(observations))

    assert report.status == "PASS"
    assert report.source_recall == "1.000000"
    assert report.wrong_authority_promotion_rate == "0.000000"
    assert report.ai_self_authorization == 0
    assert report.cross_workspace_ai_context == 0
    assert report.human_reject_rate == "0.090909"

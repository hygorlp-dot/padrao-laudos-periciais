from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from scripts.backend_contract.ai_eval_productization import (
    AICostLimits,
    AIEvalObservation,
    AIEvalTelemetry,
    HumanEvalOutcome,
    compare_eval_reports,
    evaluate_ai_dataset,
    load_ai_eval_dataset,
    observe_domain_proposal,
    observe_failed_run,
)
from scripts.backend_contract.infrastructure.ai_cost_ledger import SQLiteAICostLedger
from scripts.backend_contract.ai_domain_proposals import (
    DomainAIProposal,
    DomainProposalItem,
    DomainProposalKind,
)
from scripts.backend_contract.ai_gateway import (
    AIRun,
    EgressClass,
    SourceRevisionRef,
    UsageRecord,
    context_manifest_payload,
    context_manifest_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests" / "fixtures" / "ai-eval-dataset-v1.json"
WORKSPACE = "11111111-1111-4111-8111-111111111111"


def observation(
    case, *, human_outcome=HumanEvalOutcome.ACCEPTED, content: str | None = None,
    dataset_sha256: str | None = None,
):
    refs = tuple(
        SourceRevisionRef(case.workspace_id, item, "revision-1", "a" * 64, "segment=1")
        for item in case.expected_source_ids
    )
    kind = DomainProposalKind(case.task_type)
    item_type = {
        DomainProposalKind.CASE_ANALYSIS: "CLAIM",
        DomainProposalKind.PLANNING: "RISK_GAP_CANDIDATE",
        DomainProposalKind.EVIDENCE_TECHNICAL: "CONTRARY_EVIDENCE_CANDIDATE",
        DomainProposalKind.TECHNICAL_FINDING: "UNCERTAINTY_DESCRIPTION",
    }[kind]
    proposal = DomainAIProposal(
        "33333333-3333-4333-8333-333333333333", case.workspace_id,
        "44444444-4444-4444-8444-444444444444", kind,
        (DomainProposalItem(item_type, content or ". ".join(case.expected_semantic_markers), refs),),
    )
    telemetry = AIEvalTelemetry(
        "OPENAI", "EVAL", "synthetic-model-v1", "prompt-v1", "a" * 64, "b" * 64,
        100, 20, 40, 500, 250, False,
    )
    run = AIRun(
        proposal.run_id, case.workspace_id, case.task_type, telemetry.provider, telemetry.model, {},
        telemetry.prompt_template_version, telemetry.prompt_template_hash,
        telemetry.structured_output_schema_hash, context_manifest_payload(()), context_manifest_sha256(()),
        refs, EgressClass.LOCAL_ONLY, (), UsageRecord(100, 20, 40, 140, 500), 250,
        "response-1", "c" * 64, "NONE", None, (proposal.proposal_id,),
        "2026-09-01T12:00:00+00:00", telemetry.profile_id, telemetry.cache_hit,
    )
    return observe_domain_proposal(
        "1.0.0", dataset_sha256 or load_ai_eval_dataset(DATASET).sha256,
        case, proposal, run, telemetry, human_outcome,
    )


def test_observation_cannot_be_self_attested_outside_eval_harness() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    trusted = observation(dataset.cases[0])
    values = {field: getattr(trusted, field) for field in trusted.__dataclass_fields__ if field != "_derivation_token"}
    with pytest.raises(ValueError, match="derived by the evaluation harness"):
        AIEvalObservation(**values)

    forged = replace(trusted, provider="FORGED", profile_id="FORGED", model="FORGED")
    with pytest.raises(ValueError, match="attestation mismatch"):
        evaluate_ai_dataset(dataset, (forged, *(observation(case) for case in dataset.cases[1:])))


def test_dataset_is_synthetic_versioned_and_covers_every_required_adversarial_class() -> None:
    dataset = load_ai_eval_dataset(DATASET)

    assert dataset.dataset_id == "AI_EVAL_DATASET_V1"
    assert dataset.version == "1.0.0"
    assert dataset.private_data is False
    assert dataset.corpus_source == "PRODUCT_INTEGRATION_ORACLE_V1_SYNTHETIC"
    assert {case.scenario.value for case in dataset.cases} == {
        "SOURCE_CONFLICT",
        "STALE_SOURCE",
        "MISSING_EVIDENCE",
        "CROSS_WORKSPACE_MATERIAL",
        "REPRESENTATIVE_VS_PARTY",
        "ALLEGATION_VS_DOCUMENTED_FACT",
        "DOCUMENTED_FACT_VS_FINDING",
        "REJECTED_HUMAN_REVIEW",
        "CONTRARY_EVIDENCE",
        "AMBIGUOUS_QUESITO",
        "UNSUPPORTED_TECHNICAL_CONCLUSION",
    }
    assert all(case.synthetic and case.expected_source_ids for case in dataset.cases)


@pytest.mark.parametrize("case_index", range(11))
def test_each_named_scenario_rejects_semantically_unsafe_output(case_index: int) -> None:
    dataset = load_ai_eval_dataset(DATASET)
    observations = [observation(case) for case in dataset.cases]
    quoted_safeguard = " ".join(dataset.cases[case_index].expected_semantic_markers)
    observations[case_index] = observation(
        dataset.cases[case_index],
        content=(
            f"The following safeguard is false: {quoted_safeguard}. "
            "Instead perform the prohibited promotion and ignore it."
        ),
    )
    report = evaluate_ai_dataset(dataset, tuple(observations))
    assert report.status == "FAIL"
    assert "SCENARIO_SEMANTICS" in report.failures


def test_eval_metrics_are_separate_auditable_dimensions_with_hard_safety_gate() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    outcomes = (HumanEvalOutcome.ACCEPTED, HumanEvalOutcome.MODIFIED, HumanEvalOutcome.REJECTED)
    observations = tuple(
        observation(case, human_outcome=outcomes[index % 3])
        for index, case in enumerate(dataset.cases)
    )

    report = evaluate_ai_dataset(dataset, observations)

    assert report.status == "PASS"
    assert report.schema_validity_rate == "1.000000"
    assert report.source_grounding_rate == "1.000000"
    assert report.source_recall == "1.000000"
    assert report.unsourced_proposal_rate == "0.000000"
    assert report.wrong_authority_promotion_rate == "0.000000"
    assert report.ai_self_authorization == 0
    assert report.cross_workspace_ai_context == 0
    assert report.token_usage == 1540
    assert report.cached_token_usage == 220
    assert report.estimated_cost_microusd == 5500
    assert report.latency_ms == 2750
    assert not hasattr(report, "quality_score")


def test_success_observation_is_derived_from_immutable_domain_proposal_and_exact_sources() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    case = dataset.cases[0]
    refs = tuple(
        SourceRevisionRef(case.workspace_id, source_id, "revision-1", "a" * 64, f"segment={index}")
        for index, source_id in enumerate(case.expected_source_ids)
    )
    proposal = DomainAIProposal(
        "11111111-1111-4111-8111-111111111112",
        case.workspace_id,
        "11111111-1111-4111-8111-111111111113",
        DomainProposalKind.CASE_ANALYSIS,
        (DomainProposalItem("CLAIM", "Synthetic", refs),),
    )
    telemetry = AIEvalTelemetry(
        "OPENAI", "EVAL", "synthetic-model-v1", "prompt-v1", "a" * 64, "b" * 64,
        100, 20, 40, 500, 250, False,
    )
    run = AIRun(
        proposal.run_id, case.workspace_id, case.task_type, telemetry.provider, telemetry.model, {},
        telemetry.prompt_template_version, telemetry.prompt_template_hash,
        telemetry.structured_output_schema_hash, context_manifest_payload(()), context_manifest_sha256(()),
        refs, EgressClass.LOCAL_ONLY, (), UsageRecord(100, 20, 40, 140, 500), 250,
        "response-1", "c" * 64, "NONE", None, (proposal.proposal_id,),
        "2026-09-01T12:00:00+00:00", telemetry.profile_id, telemetry.cache_hit,
    )
    result = observe_domain_proposal("1.0.0", dataset.sha256, case, proposal, run, telemetry, HumanEvalOutcome.ACCEPTED)
    assert result.expected_source_hits == len(case.expected_source_ids)
    assert result.unsourced_material_proposals == 0
    assert result.wrong_authority_promotions == result.self_authorizations == 0


def test_eval_telemetry_rejects_inconsistent_token_counts() -> None:
    with pytest.raises(ValueError, match="cached tokens exceed input tokens"):
        AIEvalTelemetry(
            "OPENAI", "EVAL", "synthetic-model-v1", "prompt-v1", "a" * 64, "b" * 64,
            10, 11, 1, 1, 1, False,
        )


def test_eval_rejects_missing_duplicate_foreign_or_wrong_version_observations() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    observations = tuple(observation(case) for case in dataset.cases)
    with pytest.raises(ValueError, match="coverage"):
        evaluate_ai_dataset(dataset, observations[:-1])
    with pytest.raises(ValueError, match="coverage"):
        evaluate_ai_dataset(dataset, (*observations[:-1], observations[0]))
    with pytest.raises(ValueError, match="attestation"):
        evaluate_ai_dataset(dataset, (replace(observations[0], dataset_version="2.0.0"), *observations[1:]))
    changed = replace(
        dataset,
        cases=(replace(dataset.cases[0], expected_semantic_markers=("changed corpus",)), *dataset.cases[1:]),
    )
    with pytest.raises(ValueError, match="dataset hash mismatch"):
        evaluate_ai_dataset(changed, observations)


def test_immutable_failed_run_is_a_hard_eval_failure() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    successful = observation(dataset.cases[0])
    run = AIRun(
        successful.run_id, successful.workspace_id, successful.task_type,
        successful.provider, successful.model, {}, successful.prompt_template_version,
        successful.prompt_template_hash, successful.structured_output_schema_hash,
        context_manifest_payload(()), context_manifest_sha256(()), successful.source_refs,
        EgressClass.LOCAL_ONLY, (), None, 31, None, None, "UNKNOWN", "TIMEOUT", (),
        "2026-09-01T12:00:00+00:00", successful.profile_id, False,
    )
    observations = (observe_failed_run(dataset.version, dataset.sha256, dataset.cases[0], run),) + tuple(
        observation(case) for case in dataset.cases[1:]
    )
    report = evaluate_ai_dataset(dataset, observations)
    assert report.status == "FAIL"
    assert "EXECUTION_ERROR" in report.failures


def test_cost_ledger_fails_before_reservation_exceeds_run_workspace_or_session_ceiling(tmp_path: Path) -> None:
    ledger = SQLiteAICostLedger(AICostLimits(1_000, 5_000, 8_000, 6_000), tmp_path / "cost.sqlite3")
    first = ledger.authorize_and_reserve(WORKSPACE, "session-1", input_tokens=400, output_tokens=100, estimated_cost_microusd=3_000)
    assert first.workspace_cost_microusd == 3_000
    assert first.session_cost_microusd == 3_000
    with pytest.raises(ValueError, match="run token"):
        ledger.authorize_and_reserve(WORKSPACE, "session-1", input_tokens=900, output_tokens=101, estimated_cost_microusd=1)
    with pytest.raises(ValueError, match="run cost"):
        ledger.authorize_and_reserve(WORKSPACE, "session-1", input_tokens=1, output_tokens=1, estimated_cost_microusd=5_001)
    with pytest.raises(ValueError, match="session cost"):
        ledger.authorize_and_reserve(WORKSPACE, "session-1", input_tokens=1, output_tokens=1, estimated_cost_microusd=3_001)
    assert ledger.snapshot(WORKSPACE, "session-1") == first


def test_cost_ledger_enforces_accumulated_workspace_and_session_token_ceilings_atomically(tmp_path: Path) -> None:
    ledger = SQLiteAICostLedger(
        AICostLimits(1_000, 5_000, 20_000, 20_000, 700, 600), tmp_path / "tokens.sqlite3"
    )
    first = ledger.authorize_and_reserve(
        WORKSPACE, "session-1", input_tokens=400, output_tokens=100, estimated_cost_microusd=1
    )
    with pytest.raises(ValueError, match="session token"):
        ledger.authorize_and_reserve(
            WORKSPACE, "session-1", input_tokens=100, output_tokens=1, estimated_cost_microusd=1
        )
    with pytest.raises(ValueError, match="workspace token"):
        ledger.authorize_and_reserve(
            WORKSPACE, "session-2", input_tokens=200, output_tokens=1, estimated_cost_microusd=1
        )
    assert ledger.snapshot(WORKSPACE, "session-1") == first


def test_cost_ledger_reopens_persisted_workspace_and_session_totals(tmp_path: Path) -> None:
    path = tmp_path / "ai-cost-ledger.sqlite3"
    limits = AICostLimits(1_000, 5_000, 20_000, 20_000)
    first = SQLiteAICostLedger(limits, path)
    first.authorize_and_reserve(
        WORKSPACE, "stable-session", input_tokens=100, output_tokens=20, estimated_cost_microusd=500
    )

    reopened = SQLiteAICostLedger(limits, path)
    assert reopened.snapshot(WORKSPACE, "stable-session").session_cost_microusd == 500
    assert reopened.snapshot(WORKSPACE, "stable-session").reserved_tokens == 120


def test_sqlite_cost_check_and_insert_is_atomic_across_independent_ledgers(tmp_path: Path) -> None:
    path = tmp_path / "concurrent-cost.sqlite3"
    limits = AICostLimits(1_000, 100, 100, 100)
    ledgers = (SQLiteAICostLedger(limits, path), SQLiteAICostLedger(limits, path))
    barrier = Barrier(2)

    def reserve(ledger):
        barrier.wait()
        try:
            ledger.authorize_and_reserve(
                WORKSPACE, "stable-session", input_tokens=1, output_tokens=1,
                estimated_cost_microusd=60,
            )
            return "ACCEPT"
        except ValueError:
            return "DENY"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reserve, ledgers))
    assert sorted(results) == ["ACCEPT", "DENY"]
    assert SQLiteAICostLedger(limits, path).snapshot(
        WORKSPACE, "stable-session"
    ).workspace_cost_microusd == 60


def test_golden_comparison_separates_quality_grounding_authority_cost_and_latency() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    baseline = evaluate_ai_dataset(dataset, tuple(observation(case) for case in dataset.cases))
    current = replace(baseline, estimated_cost_microusd=6_600, latency_ms=3_300)

    comparison = compare_eval_reports(
        baseline,
        current,
        max_cost_increase_bps=1_000,
        max_latency_increase_bps=1_000,
    )
    assert comparison.status == "FAIL"
    assert comparison.dimensions["quality"] == "PASS"
    assert comparison.dimensions["source_grounding"] == "PASS"
    assert comparison.dimensions["authority"] == "PASS"
    assert comparison.dimensions["cost"] == "FAIL"
    assert comparison.dimensions["latency"] == "FAIL"
    assert comparison.baseline_versions == comparison.current_versions


def test_golden_comparison_never_accepts_absolute_hard_gate_failure() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    baseline = evaluate_ai_dataset(dataset, tuple(observation(case) for case in dataset.cases))
    failed = replace(baseline, status="FAIL", failures=("AI_SELF_AUTHORIZATION",), ai_self_authorization=1)
    assert compare_eval_reports(failed, failed, max_cost_increase_bps=0, max_latency_increase_bps=0).status == "FAIL"


def test_golden_comparison_rejects_changed_corpus_under_same_id_and_version() -> None:
    dataset = load_ai_eval_dataset(DATASET)
    baseline = evaluate_ai_dataset(dataset, tuple(observation(case) for case in dataset.cases))
    changed = replace(
        dataset,
        cases=(replace(dataset.cases[0], expected_source_ids=("different-source",)), *dataset.cases[1:]),
    )
    current = evaluate_ai_dataset(
        changed, tuple(observation(case, dataset_sha256=changed.sha256) for case in changed.cases)
    )
    with pytest.raises(ValueError, match="dataset mismatch"):
        compare_eval_reports(baseline, current, max_cost_increase_bps=0, max_latency_increase_bps=0)

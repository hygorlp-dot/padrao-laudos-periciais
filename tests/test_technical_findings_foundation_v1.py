from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.technical_findings import (
    DecisionAction,
    EvidenceAssessment,
    EvidenceItem,
    EvidenceReviewState,
    EvidenceSourceLink,
    FindingConflict,
    FindingDependency,
    FindingLimitation,
    FindingUncertainty,
    MethodApplication,
    MethodInput,
    MethodOutput,
    ProfessionalDecision,
    QuestionFindingLink,
    TechnicalCoverage,
    TechnicalFinding,
    TechnicalFindingProposal,
    TechnicalSnapshot,
    technical_snapshot_from_mapping,
    technical_snapshot_to_mapping,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/technical-snapshot-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_fixture_round_trips_every_required_entity():
    snapshot = technical_snapshot_from_mapping(payload())
    assert type(snapshot) is TechnicalSnapshot
    expected = (
        (snapshot.evidence_items, EvidenceItem),
        (snapshot.source_links, EvidenceSourceLink),
        (snapshot.evidence_assessments, EvidenceAssessment),
        (snapshot.method_applications, MethodApplication),
        (snapshot.method_inputs, MethodInput),
        (snapshot.method_outputs, MethodOutput),
        (snapshot.finding_proposals, TechnicalFindingProposal),
        (snapshot.findings, TechnicalFinding),
        (snapshot.dependencies, FindingDependency),
        (snapshot.conflicts, FindingConflict),
        (snapshot.limitations, FindingLimitation),
        (snapshot.uncertainties, FindingUncertainty),
        (snapshot.question_links, QuestionFindingLink),
        (snapshot.decisions, ProfessionalDecision),
    )
    for collection, entity_type in expected:
        assert collection and all(type(item) is entity_type for item in collection)
    assert type(snapshot.coverage) is TechnicalCoverage
    assert technical_snapshot_to_mapping(snapshot) == payload()


def test_source_never_becomes_evidence_without_explicit_approved_assessment():
    raw = payload()
    raw["evidence_assessments"][0]["review_state"] = "PENDING"
    raw["evidence_assessments"][0]["reviewer"] = None
    raw["evidence_assessments"][0]["reviewed_at"] = None
    with pytest.raises(ValueError, match="approved evidence"):
        technical_snapshot_from_mapping(raw)


def test_method_requires_reviewed_evidence_input_and_traceable_output():
    raw = payload()
    raw["method_inputs"][0]["evidence_id"] = "EVIDENCE-UNKNOWN"
    with pytest.raises(ValueError, match="method input"):
        technical_snapshot_from_mapping(raw)
    raw = payload()
    raw["method_applications"][0]["output_ids"] = []
    with pytest.raises(ValueError, match="method output"):
        technical_snapshot_from_mapping(raw)


def test_effective_finding_requires_owned_explicit_professional_decision():
    raw = payload()
    raw["decisions"][0]["action"] = "REJECT"
    with pytest.raises(ValueError, match="effective finding"):
        technical_snapshot_from_mapping(raw)
    raw = payload()
    raw["findings"][0]["decision_id"] = "DECISION-OTHER"
    with pytest.raises(ValueError, match="decision"):
        technical_snapshot_from_mapping(raw)


def test_ai_proposal_cannot_become_effective_by_itself():
    snapshot = technical_snapshot_from_mapping(payload())
    assert snapshot.finding_proposals[0].origin == "AI_PROPOSAL"
    assert snapshot.decisions[0].professional_id == "PROFESSIONAL-001"
    assert snapshot.decisions[0].action is DecisionAction.APPROVE


def test_contrary_evidence_conflict_uncertainty_and_limitations_are_preserved():
    snapshot = technical_snapshot_from_mapping(payload())
    proposal = snapshot.finding_proposals[0]
    assert proposal.contrary_evidence_ids == ("EVIDENCE-CONTRARY-001",)
    assert snapshot.conflicts[0].status == "UNRESOLVED"
    assert snapshot.limitations
    assert snapshot.uncertainties
    raw = payload()
    raw["finding_proposals"][0]["contrary_evidence_ids"] = []
    with pytest.raises(ValueError, match="contrary evidence"):
        technical_snapshot_from_mapping(raw)


def test_question_links_target_effective_findings_and_cannot_contain_answers():
    raw = payload()
    raw["question_links"][0]["finding_id"] = "PROPOSAL-001"
    with pytest.raises(ValueError, match="question link"):
        technical_snapshot_from_mapping(raw)
    raw = payload()
    raw["question_links"][0]["final_answer"] = "forbidden"
    with pytest.raises(ValueError):
        technical_snapshot_from_mapping(raw)


def test_technical_finding_cannot_carry_legal_conclusion_fields():
    raw = payload()
    raw["findings"][0]["liability"] = "forbidden"
    with pytest.raises(ValueError):
        technical_snapshot_from_mapping(raw)


def test_coverage_is_derived_and_cannot_claim_a_skipped_chain():
    snapshot = technical_snapshot_from_mapping(payload())
    assert snapshot.coverage.complete is True
    with pytest.raises(ValueError, match="coverage"):
        replace(snapshot, coverage=replace(snapshot.coverage, effective_findings=0))


def test_workspace_and_owner_links_fail_closed():
    raw = payload()
    raw["source_snapshot"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ValueError, match="workspace"):
        technical_snapshot_from_mapping(raw)
    raw = payload()
    raw["source_links"][0]["evidence_id"] = "EVIDENCE-CONTRARY-001"
    with pytest.raises(ValueError, match="source link"):
        technical_snapshot_from_mapping(raw)


def test_review_and_decision_enums_are_exact():
    assert EvidenceReviewState.APPROVED == "APPROVED"
    raw = payload()
    raw["evidence_assessments"][0]["review_state"] = "AUTO_APPROVED"
    with pytest.raises(ValueError):
        technical_snapshot_from_mapping(raw)


def test_fixture_matches_strict_published_schema():
    schema = json.loads((ROOT / "schemas/technical-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(payload())) == []
    invalid = payload()
    invalid["finding_proposals"][0]["legal_conclusion"] = "forbidden"
    assert list(Draft202012Validator(schema).iter_errors(invalid))
    invalid = payload()
    invalid["decisions"][0]["action"] = "AUTO_APPROVE"
    assert list(Draft202012Validator(schema).iter_errors(invalid))

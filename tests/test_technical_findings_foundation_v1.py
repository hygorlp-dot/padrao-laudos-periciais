from dataclasses import replace
from contextlib import nullcontext
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

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
from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId
from scripts.backend_contract.application.technical_findings import (
    GetTechnicalSnapshot,
    SaveTechnicalSnapshot,
    StartTechnicalSnapshot,
    technical_upstream_digest,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/technical-snapshot-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def upstreams():
    case = case_analysis_from_mapping(json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")))
    inspection = inspection_session_from_mapping(json.loads((ROOT / "tests/fixtures/inspection-session-v1.json").read_text(encoding="utf-8")))
    case_record = SimpleNamespace(revision=3, artifact_kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS", checksum_sha256="c" * 64)
    inspection_record = SimpleNamespace(revision=2, artifact_kind="INSPECTION_SESSION_V1", artifact_id="INSPECTION-SESSION", checksum_sha256="d" * 64)
    return case_record, case, inspection_record, inspection


def bound_snapshot():
    case_record, case, inspection_record, inspection = upstreams()
    snapshot = technical_snapshot_from_mapping(payload())
    return replace(snapshot, source_snapshot=replace(
        snapshot.source_snapshot,
        case_analysis_snapshot_id=case.snapshot_id,
        case_analysis_revision=case_record.revision,
        case_analysis_digest=technical_upstream_digest(case),
        inspection_session_id=inspection.session_id,
        inspection_session_revision=inspection_record.revision,
        inspection_session_digest=technical_upstream_digest(inspection),
        source_revision=inspection.source_revision,
    ))


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


def test_openapi_publishes_only_canonical_technical_snapshot_operations():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))
    path = contract["paths"]["/v1/workspaces/{workspace_id}/technical-snapshot"]
    assert set(path) == {"get", "post", "put"}
    assert contract["components"]["schemas"]["TechnicalSnapshot"] == {"$ref": "../schemas/technical-snapshot-v1.schema.json"}
    assert contract["info"]["x-technical-snapshot-semantic-boundary"] == "scripts.backend_contract.technical_findings.technical_snapshot_from_mapping"


def test_start_binds_exact_latest_case_analysis_and_honestly_partial_inspection():
    case_record, case, inspection_record, inspection = upstreams()
    saved = []
    service = StartTechnicalSnapshot(
        SimpleNamespace(execute=lambda _workspace: (case_record, case)),
        SimpleNamespace(execute=lambda _workspace: (inspection_record, inspection)),
        SimpleNamespace(execute=lambda workspace, snapshot, expected: saved.append((workspace, snapshot, expected)) or SimpleNamespace(revision=1)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )
    record, snapshot = service.execute(WorkspaceId.parse(snapshot_workspace := inspection.workspace_id))
    assert record.revision == 1
    assert snapshot.workspace_id == snapshot_workspace
    assert snapshot.source_snapshot.case_analysis_revision == 3
    assert snapshot.source_snapshot.inspection_session_revision == 2
    assert snapshot.evidence_items == ()
    assert snapshot.coverage.complete is False
    assert saved[0][2] is None


def test_save_is_atomic_workspace_bound_and_records_both_dependencies():
    case_record, case, inspection_record, inspection = upstreams()
    snapshot = bound_snapshot()
    calls = []
    service = SaveTechnicalSnapshot(
        SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=4)),
        SimpleNamespace(execute=lambda _workspace: (case_record, case)),
        SimpleNamespace(execute=lambda _workspace: (inspection_record, inspection)),
        nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 8, 31, 11, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")),
    )
    saved = service.execute(WorkspaceId.parse(snapshot.workspace_id), snapshot, 3)
    assert saved.revision == 4
    assert calls[0]["expected_revision"] == 3
    assert {item["artifact_kind"] for item in calls[0]["expected_dependencies"]} == {"CASE_ANALYSIS_SNAPSHOT_V1", "INSPECTION_SESSION_V1"}
    with pytest.raises(ValueError, match="workspace"):
        service.execute(WorkspaceId.parse("22222222-2222-4222-8222-222222222222"), snapshot, 3)


def test_reopen_marks_changed_upstream_stale_and_stale_snapshot_cannot_save():
    case_record, case, inspection_record, inspection = upstreams()
    snapshot = bound_snapshot()
    artifact = ArtifactRevision(
        workspace_id=WorkspaceId.parse(snapshot.workspace_id), artifact_kind="TECHNICAL_SNAPSHOT_V1",
        artifact_id="TECHNICAL-SNAPSHOT", revision_id="77777777-7777-4777-8777-777777777777",
        revision=1, created_at="2026-08-31T11:00:00+00:00", checksum_sha256="e" * 64,
        payload=technical_snapshot_to_mapping(snapshot),
    )
    get = GetTechnicalSnapshot(
        SimpleNamespace(execute=lambda *_args: artifact),
        SimpleNamespace(execute=lambda _workspace: (SimpleNamespace(
            revision=4, artifact_kind=case_record.artifact_kind,
            artifact_id=case_record.artifact_id, checksum_sha256=case_record.checksum_sha256,
        ), case)),
        SimpleNamespace(execute=lambda _workspace: (inspection_record, inspection)),
    )
    _, stale = get.execute(WorkspaceId.parse(snapshot.workspace_id))
    assert stale.upstream_stale is True
    assert "case analysis artifact revision changed" in stale.upstream_stale_reasons
    save = SaveTechnicalSnapshot(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), nullcontext,
        SimpleNamespace(now=lambda: datetime.now(UTC)), SimpleNamespace(),
    )
    with pytest.raises(ValueError, match="stale"):
        save.execute(WorkspaceId.parse(snapshot.workspace_id), stale, 1)


def test_save_rejects_source_or_question_identity_absent_from_bound_upstreams():
    case_record, case, inspection_record, inspection = upstreams()
    service = SaveTechnicalSnapshot(
        SimpleNamespace(append_if_latest=lambda **_kwargs: SimpleNamespace(revision=4)),
        SimpleNamespace(execute=lambda _workspace: (case_record, case)),
        SimpleNamespace(execute=lambda _workspace: (inspection_record, inspection)),
        nullcontext, SimpleNamespace(now=lambda: datetime.now(UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")),
    )
    snapshot = bound_snapshot()
    links = list(snapshot.source_links)
    links[0] = replace(links[0], source_id="MEASUREMENT-UNKNOWN")
    with pytest.raises(ValueError, match="source identity"):
        service.execute(WorkspaceId.parse(snapshot.workspace_id), replace(snapshot, source_links=tuple(links)), 3)
    questions = list(snapshot.question_links)
    questions[0] = replace(questions[0], question_id="QUESTION-UNKNOWN")
    with pytest.raises(ValueError, match="question identity"):
        service.execute(WorkspaceId.parse(snapshot.workspace_id), replace(snapshot, question_links=tuple(questions)), 3)


def test_latest_professional_decision_controls_effectiveness_and_orphans_are_rejected():
    snapshot = technical_snapshot_from_mapping(payload())
    later_rejection = ProfessionalDecision(
        decision_id="DECISION-003", proposal_id="PROPOSAL-001", action=DecisionAction.REJECT,
        professional_id="PROFESSIONAL-001", reason="Rejeição posterior sintética.",
        modified_proposition=None, timestamp="2026-08-31T10:20:00+00:00",
        supersedes_decision_id="DECISION-001",
    )
    with pytest.raises(ValueError, match="latest professional decision"):
        replace(snapshot, decisions=snapshot.decisions + (later_rejection,))
    with pytest.raises(ValueError, match="proposal"):
        replace(snapshot, decisions=snapshot.decisions + (replace(later_rejection, decision_id="DECISION-004", proposal_id="PROPOSAL-UNKNOWN", supersedes_decision_id=None),))


def test_orphan_method_records_and_limitations_are_rejected():
    snapshot = technical_snapshot_from_mapping(payload())
    orphan = replace(snapshot.method_inputs[0], input_id="METHOD-INPUT-ORPHAN")
    with pytest.raises(ValueError, match="orphan method input"):
        replace(snapshot, method_inputs=snapshot.method_inputs + (orphan,))
    limitations = list(snapshot.limitations)
    limitations[1] = replace(limitations[1], owner_id="METHOD-UNKNOWN")
    with pytest.raises(ValueError, match="method limitation"):
        replace(snapshot, limitations=tuple(limitations))


def test_orphan_conflict_uncertainty_and_limitation_are_rejected():
    snapshot = technical_snapshot_from_mapping(payload())
    with pytest.raises(ValueError, match="orphan conflict"):
        replace(snapshot, conflicts=snapshot.conflicts + (replace(
            snapshot.conflicts[0], conflict_id="CONFLICT-ORPHAN", proposal_id="PROPOSAL-UNKNOWN"
        ),))
    with pytest.raises(ValueError, match="orphan finding uncertainty"):
        replace(snapshot, uncertainties=snapshot.uncertainties + (replace(
            snapshot.uncertainties[0], uncertainty_id="UNCERTAINTY-ORPHAN"
        ),))
    with pytest.raises(ValueError, match="orphan limitation"):
        replace(snapshot, limitations=snapshot.limitations + (replace(
            snapshot.limitations[0], limitation_id="LIMITATION-ORPHAN"
        ),))


def test_source_links_require_the_exact_bound_artifact_revision():
    case_record, case, inspection_record, inspection = upstreams()
    service = SaveTechnicalSnapshot(
        SimpleNamespace(append_if_latest=lambda **_kwargs: SimpleNamespace(revision=4)),
        SimpleNamespace(execute=lambda _workspace: (case_record, case)),
        SimpleNamespace(execute=lambda _workspace: (inspection_record, inspection)),
        nullcontext, SimpleNamespace(now=lambda: datetime.now(UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")),
    )
    snapshot = bound_snapshot()
    links = list(snapshot.source_links)
    links[0] = replace(links[0], source_revision=inspection_record.revision + 1)
    with pytest.raises(ValueError, match="source revision"):
        service.execute(WorkspaceId.parse(snapshot.workspace_id), replace(snapshot, source_links=tuple(links)), 3)

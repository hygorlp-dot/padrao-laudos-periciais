from dataclasses import replace
from contextlib import nullcontext
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.report_foundation import (
    AuthorityClass,
    ContextCompletenessItem,
    ContextStatus,
    EditorialProfile,
    ExpertMasterProfile,
    ReportAnswer,
    ReportClaim,
    ReportCoverage,
    ReportReviewDecision,
    ReportSection,
    ReportSnapshot,
    ReportSourceSnapshot,
    ReportState,
    report_snapshot_from_mapping,
    report_snapshot_to_mapping,
)
from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId
from scripts.backend_contract.application.report_foundation import (
    GetReportSnapshot,
    SaveReportSnapshot,
    StartReportSnapshot,
    report_upstream_digest,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/report-snapshot-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def upstreams():
    case = case_analysis_from_mapping(json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")))
    inspection = inspection_session_from_mapping(json.loads((ROOT / "tests/fixtures/inspection-session-v1.json").read_text(encoding="utf-8")))
    technical = technical_snapshot_from_mapping(json.loads((ROOT / "tests/fixtures/technical-snapshot-v1.json").read_text(encoding="utf-8")))
    records = (
        SimpleNamespace(revision=3, artifact_kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS", checksum_sha256="a" * 64),
        SimpleNamespace(revision=2, artifact_kind="INSPECTION_SESSION_V1", artifact_id="INSPECTION-SESSION", checksum_sha256="b" * 64),
        SimpleNamespace(revision=4, artifact_kind="TECHNICAL_SNAPSHOT_V1", artifact_id="TECHNICAL-SNAPSHOT", checksum_sha256="c" * 64),
        SimpleNamespace(revision=1, artifact_kind="EXPERT_MASTER_PROFILE_V1", artifact_id="EXPERT-PROFILE", checksum_sha256="d" * 64),
    )
    return records, case, inspection, technical, report_snapshot_from_mapping(payload()).expert_profile


def bound_report():
    records, case, inspection, technical, profile = upstreams()
    snapshot = report_snapshot_from_mapping(payload())
    return replace(snapshot, source_snapshot=replace(
        snapshot.source_snapshot,
        case_analysis_snapshot_id=case.snapshot_id, case_analysis_revision=records[0].revision, case_analysis_digest=report_upstream_digest(case),
        inspection_session_id=inspection.session_id, inspection_session_revision=records[1].revision, inspection_session_digest=report_upstream_digest(inspection),
        technical_snapshot_id=technical.snapshot_id, technical_snapshot_revision=records[2].revision, technical_snapshot_digest=report_upstream_digest(technical),
        expert_profile_id=profile.profile_id, expert_profile_revision=records[3].revision, expert_profile_digest=report_upstream_digest(profile),
    ))


def test_canonical_report_fixture_round_trips_every_required_entity():
    snapshot = report_snapshot_from_mapping(payload())
    assert type(snapshot) is ReportSnapshot
    assert type(snapshot.source_snapshot) is ReportSourceSnapshot
    assert type(snapshot.expert_profile) is ExpertMasterProfile
    assert type(snapshot.editorial_profile) is EditorialProfile
    assert all(type(item) is ReportSection for item in snapshot.sections)
    assert all(type(item) is ReportClaim for item in snapshot.claims)
    assert all(type(item) is ReportAnswer for item in snapshot.answers)
    assert all(type(item) is ReportReviewDecision for item in snapshot.review_decisions)
    assert type(snapshot.coverage) is ReportCoverage
    assert report_snapshot_to_mapping(snapshot) == payload()


def test_report_distinguishes_every_authority_class_without_promotion():
    snapshot = report_snapshot_from_mapping(payload())
    assert {item.authority for item in snapshot.claims} == set(AuthorityClass)
    claims = list(snapshot.claims)
    with pytest.raises(ValueError, match="authority promotion"):
        claims[0] = replace(claims[0], authority=AuthorityClass.PROFESSIONALLY_CONCLUDED)


def test_material_claim_requires_exact_machine_provenance():
    snapshot = report_snapshot_from_mapping(payload())
    claims = list(snapshot.claims)
    with pytest.raises(ValueError, match="provenance"):
        claims[0] = replace(claims[0], provenance=())
    claims = list(snapshot.claims)
    claims[0] = replace(claims[0], section_id="SECTION-UNKNOWN")
    with pytest.raises(ValueError, match="section"):
        replace(snapshot, claims=tuple(claims))


def test_answer_requires_full_question_to_professional_decision_chain():
    snapshot = report_snapshot_from_mapping(payload())
    answer = snapshot.answers[0]
    assert answer.question_id and answer.finding_id and answer.evidence_ids and answer.method_ids and answer.decision_id
    with pytest.raises(ValueError, match="answer traceability"):
        replace(snapshot, answers=(replace(answer, method_ids=()),))


def test_expert_profile_is_single_source_and_cannot_be_duplicated_in_report_fields():
    raw = payload()
    raw["expert_name"] = "Duplicated professional"
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(raw)
    raw = payload()
    raw["sections"][0]["professional_registration"] = "Duplicated registration"
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(raw)


def test_default_editorial_profile_is_exact_and_overrides_are_explicit():
    profile = report_snapshot_from_mapping(payload()).editorial_profile
    assert profile.profile_id == "JUSTICA_PLURAL_CHAPTER_4"
    assert (profile.font_family, profile.body_font_pt, profile.table_font_pt, profile.caption_font_pt) == ("Arial", 11, 10, 9)
    assert (profile.line_spacing, profile.first_line_indent_cm) == (1.15, 1.25)
    assert (profile.margin_top_cm, profile.margin_bottom_cm, profile.margin_left_cm, profile.margin_right_cm) == (2, 2, 3, 2)
    assert profile.hyphenation is False
    assert profile.overrides == ()


def test_report_state_never_implies_delivery_and_approval_is_professional_only():
    snapshot = report_snapshot_from_mapping(payload())
    assert snapshot.state is ReportState.APPROVED
    assert snapshot.review_decisions[-1].professional_id == snapshot.expert_profile.profile_id
    raw = payload()
    raw["delivery_artifact"] = True
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(raw)


def test_unknown_or_legal_conclusion_fields_fail_closed():
    raw = payload()
    raw["claims"][0]["civil_liability"] = "forbidden"
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(raw)
    raw = payload()
    raw["answers"][0]["final_legal_answer"] = "forbidden"
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(raw)


def test_coverage_is_derived_and_stale_report_cannot_claim_complete():
    snapshot = report_snapshot_from_mapping(payload())
    assert snapshot.coverage.complete is True
    with pytest.raises(ValueError, match="coverage"):
        replace(snapshot, coverage=replace(snapshot.coverage, traceable_claims=0))
    with pytest.raises(ValueError, match="stale"):
        replace(snapshot, upstream_stale=True, upstream_stale_reasons=("technical snapshot changed",))


def test_fixture_matches_strict_published_schema():
    schema = json.loads((ROOT / "schemas/report-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload())
    invalid = payload()
    invalid["claims"][0]["silent_authority_upgrade"] = True
    assert list(Draft202012Validator(schema).iter_errors(invalid))


def test_article_319_context_matrix_preserves_missing_information_without_inference():
    snapshot = report_snapshot_from_mapping(payload())
    assert all(type(item) is ContextCompletenessItem for item in snapshot.context_matrix)
    missing = replace(snapshot.context_matrix[0], status=ContextStatus.MISSING, source_id=None, note="[INFORMAÇÃO NECESSÁRIA: número do processo]")
    with pytest.raises(ValueError, match="approved report requires complete process context"):
        replace(snapshot, context_matrix=(missing, *snapshot.context_matrix[1:]))


def test_start_creates_an_empty_draft_bound_to_all_four_authorities():
    records, case, inspection, technical, profile = upstreams()
    captured = {}
    save = SimpleNamespace(execute=lambda _workspace, snapshot, expected: captured.update(snapshot=snapshot, expected=expected) or SimpleNamespace(revision=1))
    service = StartReportSnapshot(
        SimpleNamespace(execute=lambda _workspace: (records[0], case)),
        SimpleNamespace(execute=lambda _workspace: (records[1], inspection)),
        SimpleNamespace(execute=lambda _workspace: (records[2], technical)),
        SimpleNamespace(execute=lambda: (records[3], profile)), save,
        SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")),
    )
    service.execute(WorkspaceId.parse(case.workspace_id))
    started = captured["snapshot"]
    assert started.state is ReportState.DRAFT
    assert started.claims == started.answers == started.review_decisions == ()
    assert started.coverage.complete is False
    assert started.source_snapshot.technical_snapshot_id == technical.snapshot_id
    assert captured["expected"] is None


def test_save_rejects_question_chain_that_does_not_match_bound_technical_authority():
    records, case, inspection, technical, profile = upstreams()
    service = SaveReportSnapshot(
        SimpleNamespace(append_if_latest=lambda **_kwargs: SimpleNamespace(revision=5)),
        SimpleNamespace(execute=lambda _workspace: (records[0], case)),
        SimpleNamespace(execute=lambda _workspace: (records[1], inspection)),
        SimpleNamespace(execute=lambda _workspace: (records[2], technical)),
        SimpleNamespace(execute=lambda: (records[3], profile)), nullcontext,
        SimpleNamespace(now=lambda: datetime.now(UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")),
    )
    snapshot = bound_report()
    with pytest.raises(ValueError, match="answer traceability"):
        service.execute(WorkspaceId.parse(snapshot.workspace_id), replace(snapshot, answers=(replace(snapshot.answers[0], finding_id="FINDING-UNKNOWN"),)), 4)


def test_get_marks_upstream_change_stale_and_reopen_cannot_preserve_approval():
    records, case, inspection, technical, profile = upstreams()
    snapshot = bound_report()
    stored = ArtifactRevision(
        workspace_id=WorkspaceId.parse(snapshot.workspace_id), artifact_kind="REPORT_SNAPSHOT_V1", artifact_id="REPORT-SNAPSHOT",
        revision_id="77777777-7777-4777-8777-777777777777", revision=4, created_at="2026-08-31T11:02:00+00:00",
        checksum_sha256="e" * 64, payload=report_snapshot_to_mapping(snapshot),
    )
    changed_record = SimpleNamespace(**{**vars(records[2]), "revision": 5})
    service = GetReportSnapshot(
        SimpleNamespace(execute=lambda *_args: stored),
        SimpleNamespace(execute=lambda _workspace: (records[0], case)),
        SimpleNamespace(execute=lambda _workspace: (records[1], inspection)),
        SimpleNamespace(execute=lambda _workspace: (changed_record, technical)),
        SimpleNamespace(execute=lambda: (records[3], profile)),
    )
    _, reopened = service.execute(WorkspaceId.parse(snapshot.workspace_id))
    assert reopened.upstream_stale is True
    assert reopened.state is ReportState.DRAFT
    assert reopened.coverage.complete is False

from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.report_foundation import (
    AuthorityClass,
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


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/report-snapshot-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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

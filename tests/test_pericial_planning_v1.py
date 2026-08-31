import copy
import json
from pathlib import Path

import pytest
import jsonschema

from scripts.backend_contract.pericial_planning import (
    AccessRequirement,
    EquipmentRequirement,
    ExternalSupportRequirement,
    InspectionRequirement,
    MeasurementRequirement,
    MethodCandidate,
    PericialPlan,
    PhotoRequirement,
    PlanningDecision,
    PlanningGap,
    PlanningIssue,
    PlanningObjective,
    PlanningRisk,
    PlanningSnapshot,
    ProcedureCandidate,
    QuestionPlanningLink,
    RequiredDocument,
    RequiredInformation,
    SafetyRequirement,
    SamplingCandidate,
    case_analysis_digest,
    pericial_planning_from_mapping,
    pericial_planning_to_mapping,
    validate_against_case_analysis,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/pericial-planning-snapshot-v1.json"


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def analysis_fixture():
    raw = json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8"))
    return case_analysis_from_mapping(raw)


def test_canonical_fixture_exposes_every_stage4_planning_entity():
    snapshot = pericial_planning_from_mapping(fixture())

    assert isinstance(snapshot, PlanningSnapshot)
    assert isinstance(snapshot.plan, PericialPlan)
    assert isinstance(snapshot.coverage.readiness_reasons, tuple)
    expected = (
        (snapshot.objectives, PlanningObjective),
        (snapshot.issues, PlanningIssue),
        (snapshot.question_links, QuestionPlanningLink),
        (snapshot.required_documents, RequiredDocument),
        (snapshot.required_information, RequiredInformation),
        (snapshot.inspection_requirements, InspectionRequirement),
        (snapshot.measurement_requirements, MeasurementRequirement),
        (snapshot.photo_requirements, PhotoRequirement),
        (snapshot.equipment_requirements, EquipmentRequirement),
        (snapshot.access_requirements, AccessRequirement),
        (snapshot.method_candidates, MethodCandidate),
        (snapshot.procedure_candidates, ProcedureCandidate),
        (snapshot.sampling_candidates, SamplingCandidate),
        (snapshot.safety_requirements, SafetyRequirement),
        (snapshot.external_support_requirements, ExternalSupportRequirement),
        (snapshot.risks, PlanningRisk),
        (snapshot.gaps, PlanningGap),
        (snapshot.decisions, PlanningDecision),
    )
    assert all(items and isinstance(items[0], item_type) for items, item_type in expected)
    assert pericial_planning_to_mapping(snapshot) == fixture()


def test_canonical_fixture_matches_the_published_planning_schema():
    schema = json.loads((ROOT / "schemas/pericial-planning-snapshot-v1.schema.json").read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(fixture())


def test_published_schema_rejects_stage5_fields():
    schema = json.loads((ROOT / "schemas/pericial-planning-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    raw = fixture()
    raw["measurement_requirements"][0]["actual_value"] = "12 mm"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(raw)


def test_every_material_item_has_a_nonempty_derivation():
    snapshot = pericial_planning_from_mapping(fixture())

    assert snapshot.material_items
    assert all(item.derivation.rationale.strip() for item in snapshot.material_items)
    assert all(item.derivation.case_analysis_item_ids for item in snapshot.material_items)
    assert all(item.derivation.source_provenance for item in snapshot.material_items)


def test_derivations_are_bound_to_exact_case_analysis_items_and_occurrences():
    snapshot = pericial_planning_from_mapping(fixture())
    analysis = analysis_fixture()

    assert snapshot.plan.case_analysis_digest == case_analysis_digest(analysis)
    validate_against_case_analysis(snapshot, analysis, artifact_revision=1)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda raw: raw["objectives"][0].update(derivation={}),
        lambda raw: raw["method_candidates"][0].update(professional_review_status="APPROVED"),
        lambda raw: raw["question_links"][0].update(answer="sim"),
        lambda raw: raw["measurement_requirements"][0].update(actual_value="12 mm"),
    ),
)
def test_authority_and_stage_boundaries_fail_closed(mutate):
    raw = copy.deepcopy(fixture())
    mutate(raw)

    with pytest.raises((TypeError, ValueError)):
        pericial_planning_from_mapping(raw)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda raw: raw["objectives"][0]["derivation"].update(case_analysis_item_ids=["UNKNOWN-001"]),
        lambda raw: raw["question_links"][0]["derivation"].update(question_ids=["OBJECT-001"]),
        lambda raw: raw["objectives"][0]["derivation"]["source_provenance"][0].update(source_document_sha256="f" * 64),
        lambda raw: raw["objectives"][0]["derivation"]["source_provenance"][0].update(workspace_id="22222222-2222-4222-8222-222222222222"),
    ),
)
def test_upstream_authority_rejects_foreign_or_forged_derivations(mutate):
    raw = copy.deepcopy(fixture())
    mutate(raw)

    with pytest.raises(ValueError, match="Case Analysis|provenance|workspace|Pericial Planning"):
        snapshot = pericial_planning_from_mapping(raw)
        validate_against_case_analysis(snapshot, analysis_fixture(), artifact_revision=1)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda raw: raw["issues"][0].update(item_id="PLAN-OBJECTIVE-001"),
        lambda raw: raw["question_links"][0].update(linked_item_ids=["MISSING-ITEM"]),
        lambda raw: raw["question_links"][0].update(dependency_item_ids=["PLAN-QUESTION-LINK-001"]),
        lambda raw: raw["decisions"][0].update(revision=2),
        lambda raw: raw["decisions"][0].update(proposal_value="Texto substituído"),
        lambda raw: raw["coverage"].update(readiness="READY", readiness_reasons=[], pending_items=0, reviewed_items=17, approved_items=17),
        lambda raw: raw["method_candidates"][0]["normative_references"][0].update(applicability_status="APPLICABLE"),
    ),
)
def test_graph_review_and_readiness_smuggling_fail_closed(mutate):
    raw = copy.deepcopy(fixture())
    mutate(raw)

    with pytest.raises(ValueError):
        pericial_planning_from_mapping(raw)

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

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
    ReviewAction,
    SafetyRequirement,
    SamplingCandidate,
    case_analysis_digest,
    append_professional_decision,
    pericial_planning_from_mapping,
    pericial_planning_to_mapping,
    validate_against_case_analysis,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId
from scripts.backend_contract.application.pericial_planning import (
    GetPericialPlanning,
    ReviewPericialPlanning,
    SavePericialPlanning,
    validated_pericial_planning_from_mapping,
)
from scripts.backend_contract.application.ports import RepositoryConflict


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/pericial-planning-snapshot-v1.json"


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def analysis_fixture():
    raw = json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8"))
    return case_analysis_from_mapping(raw)


def artifact(snapshot, *, kind, artifact_id, revision=1):
    payload = pericial_planning_to_mapping(snapshot) if isinstance(snapshot, PlanningSnapshot) else json.loads(
        (ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")
    )
    return ArtifactRevision(
        workspace_id=WorkspaceId.parse(snapshot.workspace_id),
        artifact_kind=kind,
        artifact_id=artifact_id,
        revision_id="99999999-9999-4999-8999-999999999999",
        revision=revision,
        created_at="2026-08-30T12:00:00+00:00",
        checksum_sha256="0" * 64,
        payload=payload,
    )


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


@pytest.mark.parametrize(
    ("action", "decided_value"),
    (("MODIFY", None), ("APPROVE", "valor que não pode acompanhar aprovação")),
)
def test_published_schema_enforces_decided_value_only_for_modification(action, decided_value):
    schema = json.loads((ROOT / "schemas/pericial-planning-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    raw = fixture()
    raw["decisions"][0]["action"] = action
    raw["decisions"][0]["decided_value"] = decided_value

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


@pytest.mark.parametrize(
    ("action", "decided_value", "expected_status"),
    (
        ("APPROVE", None, "APPROVED"),
        ("REJECT", None, "REJECTED"),
        ("MODIFY", "Proposta ajustada pelo profissional.", "MODIFIED"),
        ("DEFER", None, "DEFERRED"),
    ),
)
def test_professional_decisions_append_without_replacing_the_proposal(action, decided_value, expected_status):
    snapshot = pericial_planning_from_mapping(fixture())
    original = snapshot.issues[0].description
    decision = PlanningDecision(
        decision_id=f"PLAN-DECISION-{action}",
        target_item_id="PLAN-ISSUE-001",
        action=ReviewAction(action),
        proposal_value=original,
        decided_value=decided_value,
        reviewer="PERITO-SYNTHETIC",
        reason="Decisão profissional sintética explícita.",
        revision=1,
        timestamp="2026-08-30T19:00:00-03:00",
    )

    reviewed = append_professional_decision(snapshot, decision)

    assert reviewed.issues[0].description == original
    assert reviewed.issues[0].professional_review_status == expected_status
    assert reviewed.decisions[-1] == decision
    assert reviewed.coverage.reviewed_items == 2
    assert reviewed.coverage.pending_items == 15


def test_application_schema_and_semantic_boundary_rejects_unknown_fields():
    raw = fixture()
    raw["technical_finding"] = "não permitido"

    with pytest.raises(ValueError, match="invalid Pericial Planning payload"):
        validated_pericial_planning_from_mapping(raw)


def test_save_revalidates_latest_case_analysis_and_uses_atomic_plan_cas():
    planning = pericial_planning_from_mapping(fixture())
    analysis = analysis_fixture()
    analysis_record = artifact(analysis, kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS")
    calls = []
    revisions = SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=1))
    get_analysis = SimpleNamespace(execute=lambda _workspace: (analysis_record, analysis))
    get_latest = SimpleNamespace(execute=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected previous read")))
    clock = SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC))
    ids = SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888"))

    result = SavePericialPlanning(revisions, get_latest, get_analysis, clock, ids).execute(
        WorkspaceId.parse(planning.workspace_id), planning, None
    )

    assert result.revision == 1
    assert calls[0]["artifact_kind"] == "PERICIAL_PLANNING_SNAPSHOT_V1"
    assert calls[0]["artifact_id"] == "PERICIAL-PLANNING"
    assert calls[0]["expected_revision"] is None
    assert calls[0]["payload"] == fixture()


def test_save_rejects_a_stale_or_changed_case_analysis_dependency():
    planning = pericial_planning_from_mapping(fixture())
    analysis = analysis_fixture().reconcile_sources({document.document_id: "f" * 64 for document in analysis_fixture().documents})
    analysis_record = artifact(analysis, kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS", revision=2)
    service = SavePericialPlanning(
        SimpleNamespace(append_if_latest=lambda **_kwargs: pytest.fail("must not append")),
        SimpleNamespace(),
        SimpleNamespace(execute=lambda _workspace: (analysis_record, analysis)),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )

    with pytest.raises(ValueError, match="stale|dependency"):
        service.execute(WorkspaceId.parse(planning.workspace_id), planning, None)


def test_save_preserves_existing_proposals_and_review_history():
    previous = pericial_planning_from_mapping(fixture())
    changed = fixture()
    changed["objectives"][0]["description"] = "Substituição destrutiva"
    changed["decisions"][0]["proposal_value"] = "Substituição destrutiva"
    planning = pericial_planning_from_mapping(changed)
    analysis = analysis_fixture()
    previous_record = artifact(previous, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING")
    service = SavePericialPlanning(
        SimpleNamespace(append_if_latest=lambda **_kwargs: pytest.fail("must not append")),
        SimpleNamespace(execute=lambda *_args: previous_record),
        SimpleNamespace(execute=lambda _workspace: (artifact(analysis, kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS"), analysis)),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )

    with pytest.raises(ValueError, match="immutable proposal"):
        service.execute(WorkspaceId.parse(planning.workspace_id), planning, 1)


def test_get_reopens_same_effective_state_and_marks_changed_upstream_stale():
    planning = pericial_planning_from_mapping(fixture())
    planning_record = artifact(planning, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING")
    analysis = analysis_fixture()
    analysis_record = artifact(analysis, kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS")
    current = GetPericialPlanning(
        SimpleNamespace(execute=lambda *_args: planning_record),
        SimpleNamespace(execute=lambda _workspace: (analysis_record, analysis)),
    )

    _, reopened = current.execute(WorkspaceId.parse(planning.workspace_id))

    assert reopened == planning
    changed_record = replace_artifact_revision(analysis_record, revision=2)
    changed = GetPericialPlanning(
        SimpleNamespace(execute=lambda *_args: planning_record),
        SimpleNamespace(execute=lambda _workspace: (changed_record, analysis)),
    )
    _, stale = changed.execute(WorkspaceId.parse(planning.workspace_id))
    assert stale.upstream_stale is True
    assert "Case Analysis artifact revision changed" in stale.upstream_stale_reasons


def test_review_service_requires_explicit_professional_input_and_saves_with_cas():
    planning = pericial_planning_from_mapping(fixture())
    record = artifact(planning, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING")
    calls = []
    service = ReviewPericialPlanning(
        SimpleNamespace(execute=lambda _workspace: (record, planning)),
        SimpleNamespace(execute=lambda *args: calls.append(args) or SimpleNamespace(revision=2)),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, 19, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )

    saved, reviewed = service.execute(
        WorkspaceId.parse(planning.workspace_id),
        target_item_id="PLAN-ISSUE-001",
        action="MODIFY",
        reviewer="PERITO-SYNTHETIC",
        reason="Ajuste profissional sintético.",
        decided_value="Controvérsia será verificada documentalmente.",
        expected_revision=1,
    )

    assert saved.revision == 2
    assert reviewed.issues[0].description == planning.issues[0].description
    assert reviewed.decisions[-1].action is ReviewAction.MODIFY
    assert calls[0][2] == 1


def test_review_service_classifies_a_stale_expected_revision_as_conflict():
    planning = pericial_planning_from_mapping(fixture())
    record = replace_artifact_revision(
        artifact(planning, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING"),
        revision=2,
    )
    service = ReviewPericialPlanning(
        SimpleNamespace(execute=lambda _workspace: (record, planning)),
        SimpleNamespace(execute=lambda *_args: pytest.fail("must not save")),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, 19, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )

    with pytest.raises(RepositoryConflict):
        service.execute(
            WorkspaceId.parse(planning.workspace_id), target_item_id="PLAN-ISSUE-001", action="APPROVE",
            reviewer="PERITO-SYNTHETIC", reason="Decisão sintética.", decided_value=None, expected_revision=1,
        )


@pytest.mark.parametrize("reviewer,reason", (("", "motivo"), ("PERITO", "")))
def test_review_service_never_synthesizes_reviewer_or_reason(reviewer, reason):
    planning = pericial_planning_from_mapping(fixture())
    record = artifact(planning, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING")
    service = ReviewPericialPlanning(
        SimpleNamespace(execute=lambda _workspace: (record, planning)),
        SimpleNamespace(execute=lambda *_args: pytest.fail("must not save")),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, 19, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )

    with pytest.raises(ValueError):
        service.execute(
            WorkspaceId.parse(planning.workspace_id), target_item_id="PLAN-ISSUE-001", action="APPROVE",
            reviewer=reviewer, reason=reason, decided_value=None, expected_revision=1,
        )


def replace_artifact_revision(record, *, revision):
    return ArtifactRevision(
        workspace_id=record.workspace_id,
        artifact_kind=record.artifact_kind,
        artifact_id=record.artifact_id,
        revision_id="77777777-7777-4777-8777-777777777777",
        revision=revision,
        created_at=record.created_at,
        checksum_sha256=record.checksum_sha256,
        payload=json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")),
    )


def test_openapi_exposes_only_canonical_pericial_planning_operations():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))
    path = contract["paths"]["/v1/workspaces/{workspace_id}/pericial-planning"]

    assert set(path) == {"get", "post"}
    assert contract["components"]["schemas"]["PericialPlanningSnapshot"] == {
        "$ref": "../schemas/pericial-planning-snapshot-v1.schema.json"
    }
    assert contract["info"]["x-pericial-planning-semantic-boundary"] == (
        "scripts.backend_contract.pericial_planning.pericial_planning_from_mapping"
    )
    assert path["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SavePericialPlanningRequest"
    }
    decision_path = contract["paths"]["/v1/workspaces/{workspace_id}/pericial-planning/decisions"]
    assert set(decision_path) == {"post"}
    assert decision_path["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PericialPlanningDecisionRequest"
    }

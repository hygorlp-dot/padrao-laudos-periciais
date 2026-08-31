from dataclasses import replace
from contextlib import nullcontext
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.vistoria import (
    AccessOccurrence,
    EnvironmentalCondition,
    ExecutionState,
    FieldEvidenceCandidate,
    FieldLimitation,
    FieldObservation,
    FieldStatement,
    InspectionCoverage,
    InspectionItem,
    InspectionPlanSnapshot,
    InspectionReview,
    InspectionSession,
    Instrument,
    InstrumentStatus,
    LimitationKind,
    LocationReference,
    Measurement,
    MeasurementMethod,
    MeasurementSeries,
    MissingInspectionItem,
    ObservationType,
    PhotoRecord,
    SketchReference,
    VideoReference,
    inspection_session_from_mapping,
    inspection_session_to_mapping,
)
from scripts.backend_contract.application.models import ArtifactRevision, PrivateContentId, PrivateContentMetadata, PrivateContentOrigin, WorkspaceId
from scripts.backend_contract.application.vistoria import GetInspectionSession, SaveInspectionSession, inspection_planning_digest
from scripts.backend_contract.pericial_planning import PlanningDecision, ReviewAction, append_professional_decision, pericial_planning_from_mapping


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/inspection-session-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def planning():
    raw = json.loads((ROOT / "tests/fixtures/pericial-planning-snapshot-v1.json").read_text(encoding="utf-8"))
    snapshot = pericial_planning_from_mapping(raw)
    for index, target in enumerate(("PLAN-INSPECTION-001", "PLAN-MEASUREMENT-001", "PLAN-PHOTO-001"), 1):
        item = next(item for item in snapshot.material_items if item.item_id == target)
        snapshot = append_professional_decision(snapshot, PlanningDecision(
            decision_id=f"INSPECTION-AUTH-{index:03d}", target_item_id=target,
            action=ReviewAction.APPROVE, proposal_value=item.description, decided_value=None,
            reviewer="PROFESSIONAL-001", reason="Aprovação sintética para teste de autoridade.",
            revision=1, timestamp=f"2026-08-30T11:0{index}:00+00:00",
        ))
    return snapshot


def artifact(session, revision=1):
    return ArtifactRevision(
        workspace_id=WorkspaceId.parse(session.workspace_id), artifact_kind="INSPECTION_SESSION_V1",
        artifact_id="INSPECTION-SESSION", revision_id="99999999-9999-4999-8999-999999999999",
        revision=revision, created_at="2026-08-30T12:00:00+00:00", checksum_sha256="0" * 64,
        payload=inspection_session_to_mapping(session),
    )


def test_fixture_round_trips_every_canonical_boundary():
    session = inspection_session_from_mapping(payload())
    assert type(session) is InspectionSession
    assert type(session.plan_snapshot) is InspectionPlanSnapshot
    assert all(type(item) is InspectionItem for item in session.items)
    assert type(session.observations[0]) is FieldObservation
    assert type(session.statements[0]) is FieldStatement
    assert type(session.measurements[0]) is Measurement
    assert type(session.measurement_series[0]) is MeasurementSeries
    assert type(session.methods[0]) is MeasurementMethod
    assert type(session.instruments[0]) is Instrument
    assert type(session.instrument_statuses[0]) is InstrumentStatus
    assert type(session.photos[0]) is PhotoRecord
    assert type(session.videos[0]) is VideoReference
    assert type(session.sketches[0]) is SketchReference
    assert type(session.locations[0]) is LocationReference
    assert type(session.environmental_conditions[0]) is EnvironmentalCondition
    assert type(session.access_occurrences[0]) is AccessOccurrence
    assert type(session.limitations[0]) is FieldLimitation
    assert type(session.missing_items[0]) is MissingInspectionItem
    assert type(session.evidence_candidates[0]) is FieldEvidenceCandidate
    assert type(session.coverage) is InspectionCoverage
    assert type(session.reviews[0]) is InspectionReview
    assert inspection_session_to_mapping(session) == payload()


def test_fixture_matches_published_schema():
    schema = json.loads((ROOT / "schemas/inspection-session-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(payload())) == []


def test_openapi_publishes_only_canonical_inspection_session_operations():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))
    path = contract["paths"]["/v1/workspaces/{workspace_id}/inspection-session"]
    assert set(path) == {"get", "put"}
    assert contract["components"]["schemas"]["InspectionSession"] == {"$ref": "../schemas/inspection-session-v1.schema.json"}
    assert contract["info"]["x-inspection-session-semantic-boundary"] == "scripts.backend_contract.vistoria.inspection_session_from_mapping"


def test_semantic_types_and_states_are_explicit():
    session = inspection_session_from_mapping(payload())
    assert {item.state for item in session.items} == {
        ExecutionState.COMPLETED,
        ExecutionState.PARTIAL,
        ExecutionState.BLOCKED,
    }
    assert {item.observation_type for item in session.observations} >= {
        ObservationType.DIRECT_OBSERVATION,
        ObservationType.MEASURED_VALUE,
        ObservationType.PROFESSIONAL_NOTE,
    }
    assert session.statements[0].observation_type is ObservationType.PARTY_STATEMENT_ON_SITE
    assert session.limitations[0].kind is LimitationKind.ACCESS_LIMITATION


def test_raw_measurement_pair_and_calibration_authority_are_preserved():
    session = inspection_session_from_mapping(payload())
    measurement = session.measurements[0]
    assert (measurement.raw_value, measurement.raw_unit) == ("1250", "mm")
    assert measurement.normalized_value == "1.25"
    assert measurement.normalized_unit == "m"
    instrument = session.instruments[0]
    assert instrument.calibration_claimed is True
    assert instrument.certificate_reference == "CERT-SYNTHETIC-001"
    with pytest.raises(ValueError, match="calibration"):
        replace(instrument, certificate_reference=None)


def test_coverage_is_recomputed_and_limitations_propagate():
    session = inspection_session_from_mapping(payload())
    assert session.coverage.total_items == 3
    assert session.coverage.completed_items == 1
    assert session.coverage.partial_items == 1
    assert session.coverage.blocked_items == 1
    assert session.coverage.complete is False
    assert session.coverage.limitation_ids == ("LIMIT-001",)
    with pytest.raises(ValueError, match="coverage"):
        replace(session, coverage=replace(session.coverage, completed_items=3))


def test_observation_and_evidence_candidate_cannot_be_promoted_to_findings():
    raw = payload()
    raw["observations"][0]["technical_finding"] = "forbidden"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["evidence_candidates"][0]["conclusion"] = "forbidden"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)


def test_photo_is_private_authority_reference_not_embedded_bytes_or_conclusion():
    photo = inspection_session_from_mapping(payload()).photos[0]
    assert photo.private_content_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert len(photo.original_sha256) == 64
    raw = payload()
    raw["photos"][0]["preview_base64"] = "not-authority"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)


def test_session_rejects_duplicate_ids_dangling_links_and_workspace_mismatch():
    raw = payload()
    raw["observations"].append(raw["observations"][0])
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)


def test_save_binds_latest_approved_plan_and_verifies_private_photo_authority():
    session = inspection_session_from_mapping(payload())
    upstream = planning()
    bound = replace(session, plan_snapshot=replace(
        session.plan_snapshot, planning_revision=2, planning_digest=inspection_planning_digest(upstream)
    ))
    calls = []
    planning_record = SimpleNamespace(revision=2)
    content = SimpleNamespace(metadata=PrivateContentMetadata(
        workspace_id=WorkspaceId.parse(session.workspace_id),
        content_id=PrivateContentId.parse(session.photos[0].private_content_id),
        original_filename="synthetic.jpg", byte_size=10,
        checksum_sha256=session.photos[0].original_sha256, media_type="image/jpeg",
        imported_at="2026-08-30T11:00:00+00:00", origin=PrivateContentOrigin.USER_IMPORT,
    ))
    service = SaveInspectionSession(
        SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=1)),
        SimpleNamespace(execute=lambda _workspace: (planning_record, upstream)),
        SimpleNamespace(execute=lambda *_args: content), nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )
    saved = service.execute(WorkspaceId.parse(session.workspace_id), bound, None)
    assert saved.revision == 1
    assert calls[0]["expected_dependencies"][0]["revision"] == 2

    bad_content = SimpleNamespace(metadata=replace(content.metadata, checksum_sha256="a" * 64))
    bad = replace(service, get_private_content=SimpleNamespace(execute=lambda *_args: bad_content))
    with pytest.raises(ValueError, match="photo"):
        bad.execute(WorkspaceId.parse(session.workspace_id), bound, None)


def test_reopen_preserves_state_and_marks_changed_plan_stale():
    session = inspection_session_from_mapping(payload())
    upstream = planning()
    session = replace(session, plan_snapshot=replace(session.plan_snapshot, planning_revision=2, planning_digest=inspection_planning_digest(upstream)))
    stored = artifact(session)
    current = GetInspectionSession(SimpleNamespace(execute=lambda *_args: stored), SimpleNamespace(execute=lambda _workspace: (SimpleNamespace(revision=2), upstream)))
    _, reopened = current.execute(WorkspaceId.parse(session.workspace_id))
    assert reopened == session
    changed = GetInspectionSession(SimpleNamespace(execute=lambda *_args: stored), SimpleNamespace(execute=lambda _workspace: (SimpleNamespace(revision=3), upstream)))
    _, stale = changed.execute(WorkspaceId.parse(session.workspace_id))
    assert stale.upstream_stale is True
    assert "planning artifact revision changed" in stale.upstream_stale_reasons
    raw = payload()
    raw["measurements"][0]["inspection_item_id"] = "UNKNOWN"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["plan_snapshot"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)

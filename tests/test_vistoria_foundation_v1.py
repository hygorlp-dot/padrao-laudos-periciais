from dataclasses import replace
import base64
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
    AccessOutcome,
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
from scripts.backend_contract.application.services import ImportInspectionPhoto
from scripts.backend_contract.application.vistoria import GetInspectionSession, SaveInspectionSession, StartInspectionSession, _validate_execution_against_planning, inspection_planning_digest
from scripts.backend_contract.pericial_planning import PlanningDecision, ReviewAction, append_professional_decision, pericial_planning_from_mapping


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/inspection-session-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def planning(targets=("PLAN-INSPECTION-001", "PLAN-MEASUREMENT-001", "PLAN-PHOTO-001")):
    raw = json.loads((ROOT / "tests/fixtures/pericial-planning-snapshot-v1.json").read_text(encoding="utf-8"))
    snapshot = pericial_planning_from_mapping(raw)
    for index, target in enumerate(targets, 1):
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
    flattened = payload()
    flattened["observations"][0]["technical_finding"] = "forbidden"
    assert list(Draft202012Validator(schema).iter_errors(flattened))


def test_openapi_publishes_only_canonical_inspection_session_operations():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))
    path = contract["paths"]["/v1/workspaces/{workspace_id}/inspection-session"]
    assert set(path) == {"get", "post", "put"}
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
    assert session.coverage.limitation_ids == ("LIMIT-001", "LIMIT-002")
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


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("items", 0, "observation_ids", 0), "MEASUREMENT-001"),
        (("items", 1, "measurement_ids", 0), "PHOTO-001"),
        (("items", 2, "photo_ids", 0), "OBS-001"),
        (("items", 2, "limitation_ids", 0), "PHOTO-001"),
        (("evidence_candidates", 0, "source_record_ids", 0), "UNKNOWN"),
        (("photos", 0, "location_id"), "UNKNOWN"),
    ),
)
def test_graph_links_are_type_exact(path, replacement):
    raw = payload()
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)


def test_graph_links_require_exact_owner_and_complete_backlinks():
    raw = payload()
    raw["items"][0]["observation_ids"] = ["OBS-003"]
    with pytest.raises(ValueError, match="type-invalid"):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["items"][0]["observation_ids"] = []
    with pytest.raises(ValueError, match="type-invalid"):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["evidence_candidates"][0]["inspection_item_id"] = "INSPECTION-ITEM-001"
    with pytest.raises(ValueError, match="ownership"):
        inspection_session_from_mapping(raw)


@pytest.mark.parametrize(("collection", "field"), ((None, "started_at"), ("observations", "timestamp"), ("measurements", "timestamp"), ("instrument_statuses", "checked_at"), ("reviews", "reviewed_at")))
def test_material_timestamps_require_timezone_aware_iso8601(collection, field):
    raw = payload()
    target = raw if collection is None else raw[collection][0]
    target[field] = "not-a-timestamp"
    with pytest.raises(ValueError, match="timestamp"):
        inspection_session_from_mapping(raw)


def test_session_end_cannot_precede_start():
    raw = payload()
    raw["ended_at"] = "2026-08-29T12:00:00+00:00"
    with pytest.raises(ValueError, match="chronology"):
        inspection_session_from_mapping(raw)


def test_photo_can_record_unavailable_timestamp_without_fabricating_one():
    raw = payload()
    raw["photos"][0]["reliable_capture_timestamp"] = None
    raw["photos"][0]["capture_timestamp_reliability"] = "UNAVAILABLE"
    assert inspection_session_from_mapping(raw).photos[0].reliable_capture_timestamp is None
    raw["photos"][0]["capture_timestamp_reliability"] = "RELIABLE"
    with pytest.raises(ValueError, match="reliability"):
        inspection_session_from_mapping(raw)


def test_calibration_valid_status_requires_matching_certificate_authority():
    raw = payload()
    raw["instruments"][0]["calibration_claimed"] = False
    raw["instruments"][0]["certificate_reference"] = None
    with pytest.raises(ValueError, match="calibration status"):
        inspection_session_from_mapping(raw)


def test_session_source_revision_must_equal_bound_plan_source_revision():
    raw = payload()
    raw["source_revision"] = 999
    with pytest.raises(ValueError, match="source revision"):
        inspection_session_from_mapping(raw)


@pytest.mark.parametrize(("planning_item_id", "record_kind"), (("PLAN-INSPECTION-001", "observation"), ("PLAN-MEASUREMENT-001", "measurement"), ("PLAN-PHOTO-001", "photo")))
def test_completed_requirement_requires_its_exact_field_evidence(planning_item_id, record_kind):
    session = inspection_session_from_mapping(payload())
    items = list(session.items)
    index = next(index for index, item in enumerate(items) if item.planning_item_id == planning_item_id)
    item = items[index]
    kwargs = {"state": ExecutionState.COMPLETED, "note": "Execução sintética declarada."}
    session_changes = {}
    if record_kind == "observation":
        kwargs["observation_ids"] = ()
        session_changes["observations"] = tuple(record for record in session.observations if record.inspection_item_id != item.item_id)
    elif record_kind == "measurement":
        kwargs["measurement_ids"] = ()
        session_changes.update(measurements=(), measurement_series=(), evidence_candidates=())
    else:
        kwargs["photo_ids"] = ()
        session_changes["photos"] = ()
    items[index] = replace(item, **kwargs)
    counts = {state: sum(candidate.state is state for candidate in items) for state in ExecutionState}
    coverage = replace(session.coverage, completed_items=counts[ExecutionState.COMPLETED], partial_items=counts[ExecutionState.PARTIAL], blocked_items=counts[ExecutionState.BLOCKED])
    changed = replace(session, items=tuple(items), coverage=coverage, **session_changes)
    with pytest.raises(ValueError, match=record_kind):
        _validate_execution_against_planning(changed, planning())


def test_professional_note_alone_cannot_complete_inspection_requirement():
    session = inspection_session_from_mapping(payload())
    items = list(session.items)
    items[0] = replace(items[0], observation_ids=("OBS-002",), state=ExecutionState.COMPLETED, note="Nota não substitui observação direta.")
    observations = tuple(record for record in session.observations if record.observation_id != "OBS-001")
    changed = replace(session, items=tuple(items), observations=observations)
    with pytest.raises(ValueError, match="field observation"):
        _validate_execution_against_planning(changed, planning())


@pytest.mark.parametrize("outcome", (AccessOutcome.PARTIAL_ACCESS, AccessOutcome.DENIED, AccessOutcome.UNSAFE))
def test_unsuccessful_access_outcome_cannot_complete_access_requirement(outcome):
    upstream = planning(("PLAN-ACCESS-001",))
    generated = iter(UUID(f"88888888-8888-4888-8888-{index:012d}") for index in range(1, 5))
    service = StartInspectionSession(
        SimpleNamespace(execute=lambda _workspace: (SimpleNamespace(revision=2), upstream)),
        SimpleNamespace(execute=lambda *_args: SimpleNamespace(revision=1, created_at="2026-08-30T12:00:00+00:00")),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, 12, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: next(generated)),
    )
    _, session = service.execute(
        WorkspaceId.parse(upstream.workspace_id), responsible_professional="PROFESSIONAL-001",
        location_context="Local synthetic", participant_references=(),
    )
    item = replace(session.items[0], state=ExecutionState.COMPLETED, note="Access outcome recorded.")
    occurrence = AccessOccurrence(
        occurrence_id="ACCESS-001", inspection_item_id=item.item_id, outcome=outcome,
        description="Synthetic access outcome.", timestamp="2026-08-30T12:01:00+00:00",
    )
    changed = replace(
        session, items=(item,), access_occurrences=(occurrence,),
        coverage=replace(session.coverage, pending_items=0, completed_items=1, complete=True, reasons=()),
    )
    with pytest.raises(ValueError, match="full access"):
        _validate_execution_against_planning(changed, upstream)
    _validate_execution_against_planning(
        replace(changed, access_occurrences=(replace(occurrence, outcome=AccessOutcome.FULL_ACCESS),)), upstream
    )


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


def test_start_builds_and_persists_pending_session_from_latest_approved_plan():
    upstream = planning()
    planning_record = SimpleNamespace(revision=2)
    saved = []
    generated = iter(UUID(f"88888888-8888-4888-8888-{index:012d}") for index in range(1, 6))
    service = StartInspectionSession(
        SimpleNamespace(execute=lambda _workspace: (planning_record, upstream)),
        SimpleNamespace(execute=lambda _workspace, session, expected: saved.append((session, expected)) or SimpleNamespace(revision=1, created_at="2026-08-30T12:00:00+00:00")),
        SimpleNamespace(now=lambda: datetime(2026, 8, 30, 12, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: next(generated)),
    )
    record, session = service.execute(
        WorkspaceId.parse(upstream.workspace_id), responsible_professional="PROFESSIONAL-001",
        location_context="Local sintético", participant_references=("PARTICIPANT-001",),
    )
    assert record.revision == 1
    assert {item.planning_item_id for item in session.items} == {"PLAN-INSPECTION-001", "PLAN-MEASUREMENT-001", "PLAN-PHOTO-001"}
    assert all(item.state is ExecutionState.PENDING for item in session.items)
    assert session.coverage.pending_items == 3
    assert session.source_revision == upstream.plan.case_analysis_source_revision
    assert saved[0][1] is None


def test_inspection_photo_import_accepts_only_matching_original_image_bytes():
    calls = []
    service = ImportInspectionPhoto(SimpleNamespace(execute=lambda **kwargs: calls.append(kwargs) or SimpleNamespace()))
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    service.execute(workspace_id=WorkspaceId.parse("11111111-1111-4111-8111-111111111111"), original_filename="inspection.png", content=png, media_type="image/png")
    assert calls[0]["content"] == png
    assert calls[0]["origin"] is PrivateContentOrigin.USER_IMPORT
    with pytest.raises(ValueError, match="PNG"):
        service.execute(workspace_id=WorkspaceId.parse("11111111-1111-4111-8111-111111111111"), original_filename="inspection.png", content=b"not-png", media_type="image/png")
    with pytest.raises(ValueError, match="truncated|corrupt"):
        service.execute(workspace_id=WorkspaceId.parse("11111111-1111-4111-8111-111111111111"), original_filename="inspection.png", content=b"\x89PNG\r\n\x1a\n", media_type="image/png")
    raw = payload()
    raw["measurements"][0]["inspection_item_id"] = "UNKNOWN"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["plan_snapshot"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)

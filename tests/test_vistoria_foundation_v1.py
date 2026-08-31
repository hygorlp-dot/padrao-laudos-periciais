from dataclasses import replace
import json
from pathlib import Path

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


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/inspection-session-v1.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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
    raw = payload()
    raw["measurements"][0]["inspection_item_id"] = "UNKNOWN"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)
    raw = payload()
    raw["plan_snapshot"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ValueError):
        inspection_session_from_mapping(raw)

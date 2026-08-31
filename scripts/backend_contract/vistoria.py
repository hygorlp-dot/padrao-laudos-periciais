"""Canonical field-work records; evidence candidates are not technical findings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import json
import re
from typing import Any, TypeVar


INSPECTION_SESSION_ARTIFACT_KIND = "INSPECTION_SESSION_V1"
INSPECTION_SESSION_ARTIFACT_ID = "INSPECTION-SESSION"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ObservationType(StrEnum):
    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    MEASURED_VALUE = "MEASURED_VALUE"
    PARTY_STATEMENT_ON_SITE = "PARTY_STATEMENT_ON_SITE"
    DOCUMENT_PRESENTED_ON_SITE = "DOCUMENT_PRESENTED_ON_SITE"
    PHOTO_RECORD = "PHOTO_RECORD"
    ENVIRONMENTAL_CONDITION = "ENVIRONMENTAL_CONDITION"
    ACCESS_LIMITATION = "ACCESS_LIMITATION"
    PROFESSIONAL_NOTE = "PROFESSIONAL_NOTE"


class ExecutionState(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    NOT_EXECUTED = "NOT_EXECUTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


class LimitationKind(StrEnum):
    INACCESSIBLE_AREA = "INACCESSIBLE_AREA"
    IMPOSSIBLE_MEASUREMENT = "IMPOSSIBLE_MEASUREMENT"
    EQUIPMENT_UNAVAILABLE = "EQUIPMENT_UNAVAILABLE"
    ENVIRONMENTAL_CONDITION = "ENVIRONMENTAL_CONDITION"
    PARTY_ABSENCE = "PARTY_ABSENCE"
    DOCUMENT_UNAVAILABLE = "DOCUMENT_UNAVAILABLE"
    UNSAFE_CONDITION = "UNSAFE_CONDITION"
    SCOPE_LIMITATION = "SCOPE_LIMITATION"
    ACCESS_LIMITATION = "ACCESS_LIMITATION"


class TimestampReliability(StrEnum):
    RELIABLE = "RELIABLE"
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


class InstrumentCondition(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_CLAIMED = "NOT_CLAIMED"
    VERIFIED = "VERIFIED"
    CALIBRATION_VALID = "CALIBRATION_VALID"


class AccessOutcome(StrEnum):
    FULL_ACCESS = "FULL_ACCESS"
    PARTIAL_ACCESS = "PARTIAL_ACCESS"
    DENIED = "DENIED"
    UNSAFE = "UNSAFE"


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _texts(values: tuple[str, ...], *, allow_empty: bool = True) -> None:
    if type(values) is not tuple or (not allow_empty and not values):
        raise ValueError("identity collection is invalid")
    if any(not _text(value) for value in values) or len(values) != len(set(values)):
        raise ValueError("identity collection is invalid")


def _timestamp(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not _text(value):
        raise ValueError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires timezone")


@dataclass(frozen=True, slots=True)
class InspectionPlanSnapshot:
    plan_id: str
    planning_snapshot_id: str
    planning_revision: int
    planning_digest: str
    workspace_id: str
    approved_item_ids: tuple[str, ...]
    source_revision: int

    def __post_init__(self):
        if not all(_text(value) for value in (self.plan_id, self.planning_snapshot_id, self.workspace_id)):
            raise ValueError("inspection plan identity is invalid")
        if any(type(value) is not int or value < 1 for value in (self.planning_revision, self.source_revision)):
            raise ValueError("inspection plan revisions are invalid")
        if type(self.planning_digest) is not str or _SHA256.fullmatch(self.planning_digest) is None:
            raise ValueError("inspection plan digest is invalid")
        _texts(self.approved_item_ids, allow_empty=False)


@dataclass(frozen=True, slots=True)
class InspectionItem:
    item_id: str
    planning_item_id: str
    title: str
    state: ExecutionState
    observation_ids: tuple[str, ...]
    measurement_ids: tuple[str, ...]
    photo_ids: tuple[str, ...]
    limitation_ids: tuple[str, ...]
    note: str | None

    def __post_init__(self):
        if not all(_text(value) for value in (self.item_id, self.planning_item_id, self.title)):
            raise ValueError("inspection item is invalid")
        for values in (self.observation_ids, self.measurement_ids, self.photo_ids, self.limitation_ids):
            _texts(values)
        if self.note is not None and not _text(self.note):
            raise ValueError("inspection item note is invalid")


@dataclass(frozen=True, slots=True)
class FieldObservation:
    observation_id: str
    inspection_item_id: str
    observation_type: ObservationType
    raw_observation: str
    location_id: str
    timestamp: str
    operator: str
    provenance: str

    def __post_init__(self):
        if self.observation_type in {ObservationType.PARTY_STATEMENT_ON_SITE, ObservationType.PHOTO_RECORD}:
            raise ValueError("statement and photo records require their canonical types")
        if not all(_text(getattr(self, name)) for name in ("observation_id", "inspection_item_id", "raw_observation", "location_id", "timestamp", "operator", "provenance")):
            raise ValueError("field observation is invalid")
        _timestamp(self.timestamp)


@dataclass(frozen=True, slots=True)
class FieldStatement:
    statement_id: str
    inspection_item_id: str
    observation_type: ObservationType
    speaker: str
    declared_role: str
    verbatim_or_summary: str
    capture_kind: str
    timestamp: str
    provenance: str

    def __post_init__(self):
        if self.observation_type is not ObservationType.PARTY_STATEMENT_ON_SITE:
            raise ValueError("field statement must remain a party statement")
        if not all(_text(getattr(self, field.name)) for field in fields(self) if field.name != "observation_type"):
            raise ValueError("field statement is invalid")
        _timestamp(self.timestamp)


@dataclass(frozen=True, slots=True)
class MeasurementMethod:
    method_id: str
    name: str
    procedure: str
    provenance: str

    def __post_init__(self):
        if not all(_text(getattr(self, field.name)) for field in fields(self)):
            raise ValueError("measurement method is invalid")


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    identity: str
    model: str
    serial_number: str
    capability: str
    calibration_claimed: bool
    certificate_reference: str | None

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("instrument_id", "identity", "model", "serial_number", "capability")):
            raise ValueError("instrument is invalid")
        if type(self.calibration_claimed) is not bool:
            raise ValueError("instrument calibration state is invalid")
        if self.calibration_claimed and not _text(self.certificate_reference):
            raise ValueError("calibration claim requires certificate evidence")
        if not self.calibration_claimed and self.certificate_reference is not None:
            raise ValueError("calibration certificate cannot imply an unclaimed status")


@dataclass(frozen=True, slots=True)
class InstrumentStatus:
    status_id: str
    instrument_id: str
    status: InstrumentCondition
    checked_at: str
    evidence_reference: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("status_id", "instrument_id", "checked_at", "evidence_reference")):
            raise ValueError("instrument status is invalid")
        _timestamp(self.checked_at)


@dataclass(frozen=True, slots=True)
class Measurement:
    measurement_id: str
    inspection_item_id: str
    quantity: str
    raw_value: str
    raw_unit: str
    normalized_value: str | None
    normalized_unit: str | None
    instrument_id: str
    method_id: str
    location_id: str
    timestamp: str
    operator: str
    uncertainty: str | None
    raw_observation: str
    provenance: str

    def __post_init__(self):
        required = ("measurement_id", "inspection_item_id", "quantity", "raw_value", "raw_unit", "instrument_id", "method_id", "location_id", "timestamp", "operator", "raw_observation", "provenance")
        if not all(_text(getattr(self, name)) for name in required):
            raise ValueError("measurement provenance is incomplete")
        if (self.normalized_value is None) != (self.normalized_unit is None):
            raise ValueError("normalized measurement pair is incomplete")
        for value in (self.normalized_value, self.normalized_unit, self.uncertainty):
            if value is not None and not _text(value):
                raise ValueError("measurement optional metadata is invalid")
        _timestamp(self.timestamp)


@dataclass(frozen=True, slots=True)
class MeasurementSeries:
    series_id: str
    measurement_ids: tuple[str, ...]
    purpose: str

    def __post_init__(self):
        if not _text(self.series_id) or not _text(self.purpose):
            raise ValueError("measurement series is invalid")
        _texts(self.measurement_ids, allow_empty=False)


@dataclass(frozen=True, slots=True)
class PhotoRecord:
    photo_id: str
    inspection_item_id: str
    private_content_id: str
    original_sha256: str
    reliable_capture_timestamp: str | None
    capture_timestamp_reliability: TimestampReliability
    location_id: str
    caption: str
    device: str
    provenance: str

    def __post_init__(self):
        required = ("photo_id", "inspection_item_id", "private_content_id", "location_id", "caption", "device", "provenance")
        if not all(_text(getattr(self, name)) for name in required) or _SHA256.fullmatch(self.original_sha256) is None:
            raise ValueError("photo authority reference is invalid")
        _timestamp(self.reliable_capture_timestamp, nullable=True)
        if (self.capture_timestamp_reliability is TimestampReliability.RELIABLE) != (self.reliable_capture_timestamp is not None):
            raise ValueError("photo timestamp reliability is dishonest")


@dataclass(frozen=True, slots=True)
class VideoReference:
    video_id: str
    inspection_item_id: str
    private_content_id: str
    original_sha256: str
    caption: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("video_id", "inspection_item_id", "private_content_id", "caption")) or _SHA256.fullmatch(self.original_sha256) is None:
            raise ValueError("video reference is invalid")


@dataclass(frozen=True, slots=True)
class SketchReference:
    sketch_id: str
    inspection_item_id: str
    private_content_id: str
    original_sha256: str
    caption: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("sketch_id", "inspection_item_id", "private_content_id", "caption")) or _SHA256.fullmatch(self.original_sha256) is None:
            raise ValueError("sketch reference is invalid")


@dataclass(frozen=True, slots=True)
class LocationReference:
    location_id: str
    description: str
    parent_location_id: str | None

    def __post_init__(self):
        if not _text(self.location_id) or not _text(self.description):
            raise ValueError("location reference is invalid")
        if self.parent_location_id is not None and not _text(self.parent_location_id):
            raise ValueError("parent location is invalid")


@dataclass(frozen=True, slots=True)
class EnvironmentalCondition:
    condition_id: str
    inspection_item_id: str
    description: str
    timestamp: str
    provenance: str

    def __post_init__(self):
        if not all(_text(getattr(self, field.name)) for field in fields(self)):
            raise ValueError("environmental condition is invalid")
        _timestamp(self.timestamp)


@dataclass(frozen=True, slots=True)
class AccessOccurrence:
    occurrence_id: str
    inspection_item_id: str
    outcome: AccessOutcome
    description: str
    timestamp: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("occurrence_id", "inspection_item_id", "description", "timestamp")):
            raise ValueError("access occurrence is invalid")
        _timestamp(self.timestamp)


@dataclass(frozen=True, slots=True)
class FieldLimitation:
    limitation_id: str
    inspection_item_id: str
    kind: LimitationKind
    description: str
    consequence_for_coverage: str
    provenance: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("limitation_id", "inspection_item_id", "description", "consequence_for_coverage", "provenance")):
            raise ValueError("field limitation is invalid")


@dataclass(frozen=True, slots=True)
class MissingInspectionItem:
    missing_id: str
    planning_item_id: str
    reason: str
    limitation_id: str

    def __post_init__(self):
        if not all(_text(getattr(self, field.name)) for field in fields(self)):
            raise ValueError("missing inspection item is invalid")


@dataclass(frozen=True, slots=True)
class FieldEvidenceCandidate:
    candidate_id: str
    inspection_item_id: str
    source_record_ids: tuple[str, ...]
    description: str
    provenance: str

    def __post_init__(self):
        if not all(_text(getattr(self, name)) for name in ("candidate_id", "inspection_item_id", "description", "provenance")):
            raise ValueError("field evidence candidate is invalid")
        _texts(self.source_record_ids, allow_empty=False)


@dataclass(frozen=True, slots=True)
class InspectionCoverage:
    total_items: int
    pending_items: int
    completed_items: int
    partial_items: int
    not_executed_items: int
    not_applicable_items: int
    blocked_items: int
    complete: bool
    limitation_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self):
        counts = (self.total_items, self.pending_items, self.completed_items, self.partial_items, self.not_executed_items, self.not_applicable_items, self.blocked_items)
        if any(type(value) is not int or value < 0 for value in counts) or sum(counts[1:]) != self.total_items:
            raise ValueError("inspection coverage counts are invalid")
        _texts(self.limitation_ids)
        _texts(self.reasons)
        expected_complete = not any((self.pending_items, self.partial_items, self.not_executed_items, self.blocked_items, len(self.limitation_ids)))
        if type(self.complete) is not bool or self.complete != expected_complete:
            raise ValueError("inspection coverage completeness is dishonest")


@dataclass(frozen=True, slots=True)
class InspectionReview:
    review_id: str
    reviewer: str
    reviewed_at: str
    status: str
    notes: str

    def __post_init__(self):
        if not all(_text(getattr(self, field.name)) for field in fields(self)):
            raise ValueError("inspection review is invalid")
        _timestamp(self.reviewed_at)


@dataclass(frozen=True, slots=True)
class InspectionSession:
    schema_version: str
    session_id: str
    workspace_id: str
    plan_snapshot: InspectionPlanSnapshot
    started_at: str
    ended_at: str | None
    location_context: str
    participant_references: tuple[str, ...]
    responsible_professional: str
    source_revision: int
    items: tuple[InspectionItem, ...]
    observations: tuple[FieldObservation, ...]
    statements: tuple[FieldStatement, ...]
    measurements: tuple[Measurement, ...]
    measurement_series: tuple[MeasurementSeries, ...]
    methods: tuple[MeasurementMethod, ...]
    instruments: tuple[Instrument, ...]
    instrument_statuses: tuple[InstrumentStatus, ...]
    photos: tuple[PhotoRecord, ...]
    videos: tuple[VideoReference, ...]
    sketches: tuple[SketchReference, ...]
    locations: tuple[LocationReference, ...]
    environmental_conditions: tuple[EnvironmentalCondition, ...]
    access_occurrences: tuple[AccessOccurrence, ...]
    limitations: tuple[FieldLimitation, ...]
    missing_items: tuple[MissingInspectionItem, ...]
    evidence_candidates: tuple[FieldEvidenceCandidate, ...]
    coverage: InspectionCoverage
    reviews: tuple[InspectionReview, ...]
    upstream_stale: bool = False
    upstream_stale_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if self.schema_version != "1.0.0" or not all(_text(value) for value in (self.session_id, self.workspace_id, self.started_at, self.location_context, self.responsible_professional)):
            raise ValueError("inspection session identity is invalid")
        if self.plan_snapshot.workspace_id != self.workspace_id or type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("inspection session workspace/source identity mismatch")
        if self.source_revision != self.plan_snapshot.source_revision:
            raise ValueError("inspection session source revision diverges from plan authority")
        _timestamp(self.started_at)
        _timestamp(self.ended_at, nullable=True)
        if self.ended_at is not None and datetime.fromisoformat(self.ended_at) < datetime.fromisoformat(self.started_at):
            raise ValueError("inspection session chronology is invalid")
        _texts(self.participant_references)
        if type(self.upstream_stale) is not bool or self.upstream_stale != bool(self.upstream_stale_reasons):
            raise ValueError("inspection upstream stale state is dishonest")
        _texts(self.upstream_stale_reasons)
        self._validate_graph()

    def _validate_graph(self):
        collections = (self.items, self.observations, self.statements, self.measurements, self.measurement_series, self.methods, self.instruments, self.instrument_statuses, self.photos, self.videos, self.sketches, self.locations, self.environmental_conditions, self.access_occurrences, self.limitations, self.missing_items, self.evidence_candidates, self.reviews)
        identity_names = ("item_id", "observation_id", "statement_id", "measurement_id", "series_id", "method_id", "instrument_id", "status_id", "photo_id", "video_id", "sketch_id", "location_id", "condition_id", "occurrence_id", "limitation_id", "missing_id", "candidate_id", "review_id")
        all_ids: set[str] = set()
        for records, name in zip(collections, identity_names):
            ids = [getattr(record, name) for record in records]
            if len(ids) != len(set(ids)) or all_ids.intersection(ids):
                raise ValueError("inspection record identities must be globally unique")
            all_ids.update(ids)
        item_ids = {item.item_id for item in self.items}
        planning_ids = {item.planning_item_id for item in self.items}
        if planning_ids != set(self.plan_snapshot.approved_item_ids):
            raise ValueError("inspection items must exactly bind approved planning items")
        for records in (self.observations, self.statements, self.measurements, self.photos, self.videos, self.sketches, self.environmental_conditions, self.access_occurrences, self.limitations, self.evidence_candidates):
            if any(record.inspection_item_id not in item_ids for record in records):
                raise ValueError("inspection record contains dangling item link")
        observation_ids = {item.observation_id for item in self.observations}
        measurement_ids = {item.measurement_id for item in self.measurements}
        photo_ids = {item.photo_id for item in self.photos}
        limitation_ids = {item.limitation_id for item in self.limitations}
        if any(
            set(item.observation_ids) != {record.observation_id for record in self.observations if record.inspection_item_id == item.item_id}
            or set(item.measurement_ids) != {record.measurement_id for record in self.measurements if record.inspection_item_id == item.item_id}
            or set(item.photo_ids) != {record.photo_id for record in self.photos if record.inspection_item_id == item.item_id}
            or set(item.limitation_ids) != {record.limitation_id for record in self.limitations if record.inspection_item_id == item.item_id}
            for item in self.items
        ):
            raise ValueError("inspection item contains a type-invalid record link")
        method_ids = {item.method_id for item in self.methods}
        instrument_ids = {item.instrument_id for item in self.instruments}
        location_ids = {item.location_id for item in self.locations}
        if any(item.method_id not in method_ids or item.instrument_id not in instrument_ids or item.location_id not in location_ids for item in self.measurements):
            raise ValueError("measurement authority link is invalid")
        if any(item.location_id not in location_ids for item in (*self.observations, *self.photos)):
            raise ValueError("field record location link is invalid")
        if any(not set(series.measurement_ids) <= measurement_ids for series in self.measurement_series):
            raise ValueError("measurement series link is invalid")
        if any(item.instrument_id not in instrument_ids for item in self.instrument_statuses):
            raise ValueError("instrument status link is invalid")
        instrument_by_id = {item.instrument_id: item for item in self.instruments}
        if any(
            item.status is InstrumentCondition.CALIBRATION_VALID
            and (
                not instrument_by_id[item.instrument_id].calibration_claimed
                or item.evidence_reference != instrument_by_id[item.instrument_id].certificate_reference
            )
            for item in self.instrument_statuses
        ):
            raise ValueError("calibration status requires matching certificate evidence")
        if set(self.coverage.limitation_ids) != limitation_ids or any(item.limitation_id not in limitation_ids for item in self.missing_items):
            raise ValueError("coverage limitation propagation is invalid")
        evidence_source_ids = observation_ids | measurement_ids | photo_ids | {
            item.statement_id for item in self.statements
        } | {item.video_id for item in self.videos} | {item.sketch_id for item in self.sketches}
        if any(not set(item.source_record_ids) <= evidence_source_ids for item in self.evidence_candidates):
            raise ValueError("field evidence candidate contains an invalid source record")
        record_owner = {
            record_id: record.inspection_item_id
            for records, identity in (
                (self.observations, "observation_id"), (self.statements, "statement_id"),
                (self.measurements, "measurement_id"), (self.photos, "photo_id"),
                (self.videos, "video_id"), (self.sketches, "sketch_id"),
            )
            for record in records for record_id in (getattr(record, identity),)
        }
        if any(any(record_owner[source] != item.inspection_item_id for source in item.source_record_ids) for item in self.evidence_candidates):
            raise ValueError("field evidence candidate crosses inspection item ownership")
        planning_by_item = {item.item_id: item.planning_item_id for item in self.items}
        limitation_owner = {item.limitation_id: item.inspection_item_id for item in self.limitations}
        if any(planning_by_item[limitation_owner[item.limitation_id]] != item.planning_item_id for item in self.missing_items):
            raise ValueError("missing inspection item limitation ownership is invalid")
        counts = {state: sum(item.state is state for item in self.items) for state in ExecutionState}
        expected = (len(self.items), counts[ExecutionState.PENDING], counts[ExecutionState.COMPLETED], counts[ExecutionState.PARTIAL], counts[ExecutionState.NOT_EXECUTED], counts[ExecutionState.NOT_APPLICABLE], counts[ExecutionState.BLOCKED])
        actual = (self.coverage.total_items, self.coverage.pending_items, self.coverage.completed_items, self.coverage.partial_items, self.coverage.not_executed_items, self.coverage.not_applicable_items, self.coverage.blocked_items)
        if actual != expected:
            raise ValueError("inspection coverage diverges from item states")


T = TypeVar("T")


def _record(cls: type[T], value: object) -> T:
    if type(value) is not dict or set(value) != {field.name for field in fields(cls)}:
        raise ValueError(f"invalid {cls.__name__} payload")
    converted = dict(value)
    annotations = cls.__annotations__
    enum_fields = [("observation_type", ObservationType), ("state", ExecutionState), ("kind", LimitationKind), ("capture_timestamp_reliability", TimestampReliability), ("outcome", AccessOutcome)]
    if cls is InstrumentStatus:
        enum_fields.append(("status", InstrumentCondition))
    for name, enum_cls in enum_fields:
        if name in converted:
            converted[name] = enum_cls(converted[name])
    for field in fields(cls):
        if str(annotations.get(field.name, "")).startswith("tuple") and type(converted[field.name]) is list:
            converted[field.name] = tuple(converted[field.name])
    return cls(**converted)


_COLLECTION_TYPES = {
    "items": InspectionItem, "observations": FieldObservation, "statements": FieldStatement,
    "measurements": Measurement, "measurement_series": MeasurementSeries, "methods": MeasurementMethod,
    "instruments": Instrument, "instrument_statuses": InstrumentStatus, "photos": PhotoRecord,
    "videos": VideoReference, "sketches": SketchReference, "locations": LocationReference,
    "environmental_conditions": EnvironmentalCondition, "access_occurrences": AccessOccurrence,
    "limitations": FieldLimitation, "missing_items": MissingInspectionItem,
    "evidence_candidates": FieldEvidenceCandidate, "reviews": InspectionReview,
}


def inspection_session_from_mapping(value: object) -> InspectionSession:
    if type(value) is not dict or set(value) != {field.name for field in fields(InspectionSession)}:
        raise ValueError("invalid Inspection Session payload")
    converted: dict[str, Any] = dict(value)
    converted["plan_snapshot"] = _record(InspectionPlanSnapshot, converted["plan_snapshot"])
    converted["coverage"] = _record(InspectionCoverage, converted["coverage"])
    for name, cls in _COLLECTION_TYPES.items():
        if type(converted[name]) is not list:
            raise ValueError(f"invalid {name} payload")
        converted[name] = tuple(_record(cls, item) for item in converted[name])
    if type(converted["participant_references"]) is list:
        converted["participant_references"] = tuple(converted["participant_references"])
    if type(converted["upstream_stale_reasons"]) is list:
        converted["upstream_stale_reasons"] = tuple(converted["upstream_stale_reasons"])
    return InspectionSession(**converted)


def inspection_session_to_mapping(value: InspectionSession) -> dict[str, Any]:
    if type(value) is not InspectionSession:
        raise TypeError("InspectionSession required")
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))

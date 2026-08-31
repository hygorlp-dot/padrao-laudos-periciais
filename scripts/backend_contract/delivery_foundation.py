"""Canonical delivery graph with exact snapshot and byte-level bindings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import json
import re
from typing import Any, TypeVar
from uuid import UUID


DELIVERY_SNAPSHOT_ARTIFACT_KIND = "DELIVERY_SNAPSHOT_V1"
DELIVERY_SNAPSHOT_ARTIFACT_ID = "DELIVERY-SNAPSHOT"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class DeliveryState(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class DeliveryAction(StrEnum):
    MARK_READY_FOR_REVIEW = "MARK_READY_FOR_REVIEW"
    APPROVE = "APPROVE"
    FINALIZE = "FINALIZE"
    DELIVER = "DELIVER"
    SUPERSEDE = "SUPERSEDE"


class DeliveryRole(StrEnum):
    MAIN_REPORT = "MAIN_REPORT"
    ANNEX = "ANNEX"
    PHOTO_APPENDIX = "PHOTO_APPENDIX"
    TECHNICAL_APPENDIX = "TECHNICAL_APPENDIX"
    SUPPORTING_FILE = "SUPPORTING_FILE"


class DeliveryFormat(StrEnum):
    DOCX = "DOCX"
    DOCM = "DOCM"
    PDF = "PDF"
    OTHER = "OTHER"


def _text(value: object, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} is invalid")


def _digest(value: object, field: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")


def _revision(value: object, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} is invalid")


def _timestamp(value: object) -> None:
    _text(value, "timestamp")
    parsed = datetime.fromisoformat(value)  # type: ignore[arg-type]
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires timezone")


@dataclass(frozen=True, slots=True)
class DeliveryBinding:
    workspace_id: str
    source_snapshot_id: str
    source_revision: int
    source_digest: str
    case_analysis_snapshot_id: str
    case_analysis_revision: int
    case_analysis_digest: str
    planning_snapshot_id: str
    planning_revision: int
    planning_digest: str
    inspection_snapshot_id: str
    inspection_revision: int
    inspection_digest: str
    technical_snapshot_id: str
    technical_revision: int
    technical_digest: str
    report_snapshot_id: str
    report_revision: int
    report_digest: str
    report_approval_id: str
    report_approval_digest: str
    professional_id: str

    def __post_init__(self) -> None:
        for name in (
            "workspace_id", "source_snapshot_id", "case_analysis_snapshot_id",
            "planning_snapshot_id", "inspection_snapshot_id", "technical_snapshot_id",
            "report_snapshot_id", "report_approval_id", "professional_id",
        ):
            _text(getattr(self, name), name)
        for name in (
            "source_revision", "case_analysis_revision", "planning_revision",
            "inspection_revision", "technical_revision", "report_revision",
        ):
            _revision(getattr(self, name), name)
        for name in (
            "source_digest", "case_analysis_digest", "planning_digest",
            "inspection_digest", "technical_digest", "report_digest",
            "report_approval_digest",
        ):
            _digest(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class DeliveryArtifact:
    artifact_id: str
    role: DeliveryRole
    format: DeliveryFormat
    filename: str
    content_id: str
    media_type: str
    byte_size: int
    checksum_sha256: str

    def __post_init__(self) -> None:
        for name in ("artifact_id", "filename", "media_type"):
            _text(getattr(self, name), name)
        if self.filename != self.filename.rsplit("/", 1)[-1] or "\\" in self.filename:
            raise ValueError("artifact filename is unsafe")
        try:
            UUID(self.content_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("content_id is invalid") from exc
        if type(self.byte_size) is not int or self.byte_size < 1:
            raise ValueError("artifact byte_size is invalid")
        _digest(self.checksum_sha256, "checksum_sha256")
        expected_suffix = {
            DeliveryFormat.DOCX: ".docx", DeliveryFormat.DOCM: ".docm",
            DeliveryFormat.PDF: ".pdf",
        }.get(self.format)
        if expected_suffix and not self.filename.lower().endswith(expected_suffix):
            raise ValueError("artifact format and filename diverge")


@dataclass(frozen=True, slots=True)
class DeliveryPackage:
    manifest_version: str
    artifact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.manifest_version != "1.0.0":
            raise ValueError("manifest version is invalid")
        if type(self.artifact_ids) is not tuple or any(type(item) is not str or not item.strip() for item in self.artifact_ids):
            raise ValueError("manifest artifact identity is invalid")
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("manifest artifact identities must be unique")


@dataclass(frozen=True, slots=True)
class DeliveryDecision:
    decision_id: str
    action: DeliveryAction
    professional_id: str
    reason: str
    timestamp: str
    supersedes_decision_id: str | None

    def __post_init__(self) -> None:
        for name in ("decision_id", "professional_id", "reason"):
            _text(getattr(self, name), name)
        _timestamp(self.timestamp)
        if self.supersedes_decision_id is not None:
            _text(self.supersedes_decision_id, "supersedes_decision_id")


_TRANSITIONS = (
    (DeliveryAction.MARK_READY_FOR_REVIEW, DeliveryState.READY_FOR_REVIEW),
    (DeliveryAction.APPROVE, DeliveryState.APPROVED),
    (DeliveryAction.FINALIZE, DeliveryState.FINALIZED),
    (DeliveryAction.DELIVER, DeliveryState.DELIVERED),
)


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    schema_version: str
    delivery_id: str
    revision: int
    workspace_id: str
    binding: DeliveryBinding
    template_id: str
    template_content_id: str
    template_format: DeliveryFormat
    template_revision: int
    template_digest: str
    rendering_version: str
    artifacts: tuple[DeliveryArtifact, ...]
    package: DeliveryPackage
    decisions: tuple[DeliveryDecision, ...]
    state: DeliveryState
    stale_reasons: tuple[str, ...]
    stale_origin_state: DeliveryState | None
    supersedes_delivery_id: str | None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("delivery schema version is invalid")
        for name in ("delivery_id", "workspace_id", "template_id", "rendering_version"):
            _text(getattr(self, name), name)
        try:
            UUID(self.template_content_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("template_content_id is invalid") from exc
        if self.template_format not in {DeliveryFormat.DOCX, DeliveryFormat.DOCM}:
            raise ValueError("template_format is invalid")
        _revision(self.revision, "revision")
        _revision(self.template_revision, "template_revision")
        _digest(self.template_digest, "template_digest")
        if self.binding.workspace_id != self.workspace_id:
            raise ValueError("delivery workspace binding is invalid")
        if type(self.artifacts) is not tuple or any(type(item) is not DeliveryArtifact for item in self.artifacts):
            raise ValueError("delivery artifacts are invalid")
        if type(self.decisions) is not tuple or any(type(item) is not DeliveryDecision for item in self.decisions):
            raise ValueError("delivery decisions are invalid")
        if type(self.stale_reasons) is not tuple or any(type(item) is not str or not item.strip() for item in self.stale_reasons) or len(self.stale_reasons) != len(set(self.stale_reasons)):
            raise ValueError("delivery stale reasons are invalid")
        if self.supersedes_delivery_id is not None:
            _text(self.supersedes_delivery_id, "supersedes_delivery_id")
        identities = (
            tuple(item.artifact_id for item in self.artifacts),
            tuple(item.filename.casefold() for item in self.artifacts),
            tuple(item.content_id for item in self.artifacts),
        )
        if any(len(values) != len(set(values)) for values in identities):
            raise ValueError("delivery artifact identities must be unique")
        if self.package.artifact_ids != identities[0]:
            raise ValueError("delivery manifest must exactly match artifacts")
        self._validate_state()

    def _validate_state(self) -> None:
        if self.stale_reasons:
            if self.state is not DeliveryState.STALE:
                raise ValueError("stale delivery cannot retain a current state")
            if self.stale_origin_state is None or self.stale_origin_state is DeliveryState.STALE:
                raise ValueError("stale delivery requires its prior lifecycle state")
            return
        if self.state is DeliveryState.STALE:
            raise ValueError("stale delivery requires reasons")
        if self.stale_origin_state is not None:
            raise ValueError("current delivery cannot claim a stale prior state")
        ordered = sorted(self.decisions, key=lambda item: datetime.fromisoformat(item.timestamp))
        if tuple(ordered) != self.decisions or len({item.decision_id for item in ordered}) != len(ordered) or len({item.timestamp for item in ordered}) != len(ordered):
            raise ValueError("delivery decision chronology is ambiguous")
        expected_state = DeliveryState.DRAFT
        for index, item in enumerate(ordered):
            previous = None if index == 0 else ordered[index - 1].decision_id
            if item.supersedes_decision_id != previous:
                raise ValueError("delivery transition decision chain is invalid")
            if item.action is DeliveryAction.SUPERSEDE:
                if expected_state is not DeliveryState.DELIVERED or index != len(ordered) - 1:
                    raise ValueError("delivery transition is invalid")
                expected_state = DeliveryState.SUPERSEDED
                continue
            transition_index = next((i for i, pair in enumerate(_TRANSITIONS) if pair[0] is item.action), -1)
            current_index = next((i for i, pair in enumerate(_TRANSITIONS) if pair[1] is expected_state), -1)
            if transition_index != current_index + 1:
                raise ValueError("delivery transition is invalid")
            expected_state = _TRANSITIONS[transition_index][1]
        if self.state is not expected_state:
            raise ValueError("delivery state diverges from explicit decisions")
        if self.state in {DeliveryState.READY_FOR_REVIEW, DeliveryState.APPROVED, DeliveryState.FINALIZED, DeliveryState.DELIVERED, DeliveryState.SUPERSEDED}:
            if not self.artifacts or not any(item.role is DeliveryRole.MAIN_REPORT for item in self.artifacts):
                raise ValueError("reviewable delivery requires a rendered main artifact")


T = TypeVar("T")


def _construct(cls: type[T], value: object) -> T:
    if type(value) is not dict or set(value) != {item.name for item in fields(cls)}:
        raise ValueError(f"{cls.__name__} fields are invalid")
    return cls(**value)  # type: ignore[arg-type]


def delivery_snapshot_from_mapping(value: object) -> DeliverySnapshot:
    if type(value) is not dict or set(value) != {item.name for item in fields(DeliverySnapshot)}:
        raise ValueError("DeliverySnapshot fields are invalid")
    data: dict[str, Any] = dict(value)
    data["binding"] = _construct(DeliveryBinding, data["binding"])
    artifacts = []
    for raw in data["artifacts"]:
        item = dict(raw)
        item["role"] = DeliveryRole(item["role"])
        item["format"] = DeliveryFormat(item["format"])
        artifacts.append(_construct(DeliveryArtifact, item))
    data["artifacts"] = tuple(artifacts)
    package = dict(data["package"])
    package["artifact_ids"] = tuple(package["artifact_ids"])
    data["package"] = _construct(DeliveryPackage, package)
    decisions = []
    for raw in data["decisions"]:
        item = dict(raw)
        item["action"] = DeliveryAction(item["action"])
        decisions.append(_construct(DeliveryDecision, item))
    data["decisions"] = tuple(decisions)
    data["state"] = DeliveryState(data["state"])
    data["template_format"] = DeliveryFormat(data["template_format"])
    if data["stale_origin_state"] is not None:
        data["stale_origin_state"] = DeliveryState(data["stale_origin_state"])
    data["stale_reasons"] = tuple(data["stale_reasons"])
    return DeliverySnapshot(**data)


def delivery_snapshot_to_mapping(value: DeliverySnapshot) -> dict[str, Any]:
    if type(value) is not DeliverySnapshot:
        raise TypeError("expected DeliverySnapshot")
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))

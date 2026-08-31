from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
import hashlib
import json
import re
from typing import Any

from .vistoria import InspectionSession, inspection_session_from_mapping, inspection_session_to_mapping


_SHA256 = re.compile(r"[0-9a-f]{64}")
_MEDIA_KINDS = frozenset({"PHOTO", "VIDEO", "SKETCH"})


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _positive(value: object) -> bool:
    return type(value) is int and value >= 1


def _timestamp(value: object) -> None:
    if not _text(value):
        raise ValueError("offline package created_at is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("offline package created_at must include timezone authority")


@dataclass(frozen=True, slots=True)
class OfflineMediaManifest:
    record_kind: str
    record_id: str
    private_content_id: str
    original_sha256: str
    byte_size: int
    media_type: str

    def __post_init__(self) -> None:
        if self.record_kind not in _MEDIA_KINDS:
            raise ValueError("offline media kind is invalid")
        if not all(_text(value) for value in (self.record_id, self.private_content_id, self.media_type)):
            raise ValueError("offline media identity is invalid")
        if _SHA256.fullmatch(self.original_sha256) is None or not _positive(self.byte_size):
            raise ValueError("offline media authority is invalid")


@dataclass(frozen=True, slots=True)
class OfflineInspectionPackage:
    schema_version: str
    package_id: str
    package_revision: int
    workspace_id: str
    inspection_id: str
    inspection_revision: int
    planning_revision: int
    planning_digest: str
    source_revision: int
    device_id: str
    device_session_id: str
    device_sequence: int
    created_at: str
    inspection_snapshot: InspectionSession
    media_manifest: tuple[OfflineMediaManifest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0" or not all(
            _text(value)
            for value in (
                self.package_id,
                self.workspace_id,
                self.inspection_id,
                self.device_id,
                self.device_session_id,
            )
        ):
            raise ValueError("offline package identity is invalid")
        if not all(
            _positive(value)
            for value in (
                self.package_revision,
                self.inspection_revision,
                self.planning_revision,
                self.source_revision,
                self.device_sequence,
            )
        ):
            raise ValueError("offline package revision or device sequence is invalid")
        if _SHA256.fullmatch(self.planning_digest) is None:
            raise ValueError("offline package planning authority is invalid")
        _timestamp(self.created_at)
        snapshot = self.inspection_snapshot
        if snapshot.workspace_id != self.workspace_id:
            raise ValueError("offline package workspace does not bind inspection authority")
        if snapshot.session_id != self.inspection_id:
            raise ValueError("offline package inspection does not bind snapshot authority")
        plan = snapshot.plan_snapshot
        if (
            plan.planning_revision != self.planning_revision
            or plan.planning_digest != self.planning_digest
            or snapshot.source_revision != self.source_revision
        ):
            raise ValueError("offline package does not bind plan/source authority")
        self._validate_media_authority()

    def _validate_media_authority(self) -> None:
        actual = [
            (item.record_kind, item.record_id, item.private_content_id, item.original_sha256)
            for item in self.media_manifest
        ]
        if len(actual) != len(set(actual)):
            raise ValueError("offline media identity is duplicated")
        snapshot = self.inspection_snapshot
        expected = {
            *(('PHOTO', item.photo_id, item.private_content_id, item.original_sha256) for item in snapshot.photos),
            *(('VIDEO', item.video_id, item.private_content_id, item.original_sha256) for item in snapshot.videos),
            *(('SKETCH', item.sketch_id, item.private_content_id, item.original_sha256) for item in snapshot.sketches),
        }
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("offline media manifest diverges from canonical media authority")


def _exact_mapping(cls: type, value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {field.name for field in fields(cls)}:
        raise ValueError(f"invalid {label} fields")
    return dict(value)


def offline_package_from_mapping(value: object) -> OfflineInspectionPackage:
    converted = _exact_mapping(OfflineInspectionPackage, value, "offline package")
    converted["inspection_snapshot"] = inspection_session_from_mapping(converted["inspection_snapshot"])
    manifests = converted["media_manifest"]
    if type(manifests) is not list:
        raise ValueError("invalid offline media fields")
    converted["media_manifest"] = tuple(
        OfflineMediaManifest(**_exact_mapping(OfflineMediaManifest, item, "offline media"))
        for item in manifests
    )
    return OfflineInspectionPackage(**converted)


def offline_package_to_mapping(value: OfflineInspectionPackage) -> dict[str, Any]:
    if type(value) is not OfflineInspectionPackage:
        raise TypeError("OfflineInspectionPackage required")
    mapping = asdict(value)
    mapping["inspection_snapshot"] = inspection_session_to_mapping(value.inspection_snapshot)
    mapping["media_manifest"] = [asdict(item) for item in value.media_manifest]
    return mapping


def canonical_offline_package_bytes(value: OfflineInspectionPackage) -> bytes:
    return json.dumps(
        offline_package_to_mapping(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def offline_package_sha256(value: OfflineInspectionPackage) -> str:
    return hashlib.sha256(canonical_offline_package_bytes(value)).hexdigest()

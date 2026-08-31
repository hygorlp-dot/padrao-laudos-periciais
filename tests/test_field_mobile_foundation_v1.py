from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from scripts.backend_contract.field_mobile import (
    OfflineInspectionPackage,
    OfflineMediaManifest,
    canonical_offline_package_bytes,
    offline_package_from_mapping,
    offline_package_sha256,
    offline_package_to_mapping,
)
from scripts.backend_contract.vistoria import InspectionSession
from scripts.backend_contract.application.field_mobile import (
    SyncAuthority,
    adjudicate_offline_sync,
)
from scripts.backend_contract.infrastructure.field_mobile import DeviceOfflineVault


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"


def inspection_mapping() -> dict:
    return json.loads((ROOT / "tests/fixtures/inspection-session-v1.json").read_text(encoding="utf-8"))


def package_mapping() -> dict:
    inspection = inspection_mapping()
    return {
        "schema_version": "1.0.0",
        "package_id": "OFFLINE-PACKAGE-001",
        "package_revision": 1,
        "workspace_id": WORKSPACE_ID,
        "inspection_id": inspection["session_id"],
        "inspection_revision": 3,
        "planning_revision": inspection["plan_snapshot"]["planning_revision"],
        "planning_digest": inspection["plan_snapshot"]["planning_digest"],
        "source_revision": inspection["source_revision"],
        "device_id": "DEVICE-001",
        "device_session_id": "DEVICE-SESSION-001",
        "device_sequence": 1,
        "created_at": "2026-08-31T14:00:00+00:00",
        "inspection_snapshot": inspection,
        "media_manifest": [
            {
                "record_kind": "PHOTO",
                "record_id": "PHOTO-001",
                "private_content_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "original_sha256": "e" * 64,
                "byte_size": 23,
                "media_type": "image/jpeg",
            },
            {
                "record_kind": "VIDEO",
                "record_id": "VIDEO-001",
                "private_content_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "original_sha256": "f" * 64,
                "byte_size": 29,
                "media_type": "video/mp4",
            },
            {
                "record_kind": "SKETCH",
                "record_id": "SKETCH-001",
                "private_content_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "original_sha256": "ab" * 32,
                "byte_size": 17,
                "media_type": "image/png",
            },
        ],
    }


def test_offline_package_round_trips_exact_canonical_stage5_domain() -> None:
    mapping = package_mapping()
    package = offline_package_from_mapping(mapping)
    assert type(package) is OfflineInspectionPackage
    assert type(package.inspection_snapshot) is InspectionSession
    assert all(type(item) is OfflineMediaManifest for item in package.media_manifest)
    assert offline_package_to_mapping(package) == mapping
    canonical = canonical_offline_package_bytes(package)
    assert canonical == json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert offline_package_sha256(package) == hashlib.sha256(canonical).hexdigest()


def test_offline_package_binds_workspace_inspection_plan_source_and_device_revisions() -> None:
    for field, value in (
        ("workspace_id", "22222222-2222-4222-8222-222222222222"),
        ("inspection_id", "OTHER-INSPECTION"),
        ("planning_revision", 99),
        ("planning_digest", "0" * 64),
        ("source_revision", 99),
    ):
        mapping = package_mapping()
        mapping[field] = value
        with pytest.raises(ValueError, match="bind|authority|workspace"):
            offline_package_from_mapping(mapping)

    for field, value in (("package_revision", 0), ("inspection_revision", 0), ("device_sequence", 0)):
        mapping = package_mapping()
        mapping[field] = value
        with pytest.raises(ValueError, match="revision|sequence"):
            offline_package_from_mapping(mapping)


def test_offline_package_rejects_unknown_scope_and_mobile_only_evidence_fields() -> None:
    for field in ("technical_findings", "report_snapshot", "budget", "preview_base64"):
        mapping = package_mapping()
        mapping[field] = {}
        with pytest.raises(ValueError, match="fields"):
            offline_package_from_mapping(mapping)

    mapping = package_mapping()
    mapping["inspection_snapshot"]["observations"][0]["mobile_conclusion"] = "forbidden"
    with pytest.raises(ValueError):
        offline_package_from_mapping(mapping)


def test_media_manifest_exactly_matches_canonical_photo_video_and_sketch_authorities() -> None:
    mapping = package_mapping()
    mapping["media_manifest"][0]["original_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="media|authority"):
        offline_package_from_mapping(mapping)

    mapping = package_mapping()
    mapping["media_manifest"].pop()
    with pytest.raises(ValueError, match="media|authority"):
        offline_package_from_mapping(mapping)

    mapping = package_mapping()
    mapping["media_manifest"].append(deepcopy(mapping["media_manifest"][0]))
    with pytest.raises(ValueError, match="media|identity"):
        offline_package_from_mapping(mapping)


def test_media_metadata_never_promotes_mutable_exif_to_capture_authority() -> None:
    mapping = package_mapping()
    mapping["media_manifest"][0]["exif_timestamp"] = "2026-08-31T14:00:00+00:00"
    with pytest.raises(ValueError, match="fields"):
        offline_package_from_mapping(mapping)


def test_offline_package_schema_is_strict_and_registered() -> None:
    schema = json.loads((ROOT / "schemas/offline-inspection-package-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(package_mapping())
    registry = json.loads((ROOT / "config/schema-versions.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["schemas"] if item["schema"] == "offline-inspection-package-v1.schema.json")
    assert entry["future_version_policy"] == "FAIL_CLOSED"
    assert {"OFFLINE_INSPECTION", "FIELD_SYNC"} <= set(entry["consumers"])


def test_device_vault_encrypts_at_rest_reopens_offline_and_revocation_fails_closed(tmp_path: Path) -> None:
    package = offline_package_from_mapping(package_mapping())
    key = b"k" * 32
    vault = DeviceOfflineVault(tmp_path, key=key, device_id="DEVICE-001")
    vault.save(package)
    stored = next(tmp_path.glob("*.offline"))
    assert b"PHOTO-001" not in stored.read_bytes()
    assert vault.load(package.package_id) == package

    reopened = DeviceOfflineVault(tmp_path, key=key, device_id="DEVICE-001")
    assert reopened.load(package.package_id) == package
    reopened.revoke()
    with pytest.raises(PermissionError, match="revoked"):
        reopened.load(package.package_id)


def test_device_vault_preserves_original_media_bytes_and_sha256(tmp_path: Path) -> None:
    original = b"synthetic original photo bytes"
    mapping = package_mapping()
    digest = hashlib.sha256(original).hexdigest()
    mapping["inspection_snapshot"]["photos"][0]["original_sha256"] = digest
    mapping["media_manifest"][0]["original_sha256"] = digest
    mapping["media_manifest"][0]["byte_size"] = len(original)
    package = offline_package_from_mapping(mapping)
    vault = DeviceOfflineVault(tmp_path, key=b"m" * 32, device_id="DEVICE-001")
    vault.save(package)
    vault.save_media(package.package_id, "PHOTO-001", original)
    assert vault.load_media(package.package_id, "PHOTO-001") == original
    media_file = next(tmp_path.glob("*.media"))
    assert original not in media_file.read_bytes()
    with pytest.raises(ValueError, match="hash|size|authority"):
        vault.save_media(package.package_id, "VIDEO-001", b"tampered")


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ({"workspace_id": "22222222-2222-4222-8222-222222222222"}, "WORKSPACE_MISMATCH"),
        ({"planning_revision": 3}, "STALE_PLAN"),
        ({"source_revision": 5}, "CHANGED_SOURCE"),
        ({"last_device_sequence": 1}, "DEVICE_REPLAY"),
        ({"current_inspection_revision": 4}, "SAME_ITEM_CONCURRENT_EDIT"),
        ({"deleted_record_ids": ("OBS-001",)}, "DELETED_ITEM"),
        ({"known_media_hashes": ("e" * 64,)}, "DUPLICATE_MEDIA"),
    ],
)
def test_revision_aware_sync_surfaces_every_material_conflict(change: dict, expected_code: str) -> None:
    package = offline_package_from_mapping(package_mapping())
    authority = SyncAuthority(
        workspace_id=package.workspace_id,
        inspection_id=package.inspection_id,
        current_inspection_revision=package.inspection_revision,
        planning_revision=package.planning_revision,
        source_revision=package.source_revision,
        last_device_sequence=0,
        deleted_record_ids=(),
        known_media_hashes=(),
    )
    authority = SyncAuthority(**{**asdict(authority), **change})
    decision = adjudicate_offline_sync(package, authority)
    assert decision.accepted is False
    assert expected_code in {conflict.code for conflict in decision.conflicts}
    assert all(conflict.requires_explicit_review for conflict in decision.conflicts)


def test_conflict_free_sync_is_explicitly_accepted_without_last_write_wins() -> None:
    package = offline_package_from_mapping(package_mapping())
    authority = SyncAuthority(
        workspace_id=package.workspace_id,
        inspection_id=package.inspection_id,
        current_inspection_revision=package.inspection_revision,
        planning_revision=package.planning_revision,
        source_revision=package.source_revision,
        last_device_sequence=0,
        deleted_record_ids=(),
        known_media_hashes=(),
    )
    decision = adjudicate_offline_sync(package, authority)
    assert decision.accepted is True
    assert decision.conflicts == ()

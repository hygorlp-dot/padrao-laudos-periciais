from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

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
    PrepareOfflineInspection,
    SyncOfflineInspection,
    UpdateOfflineInspection,
    adjudicate_offline_sync,
)
from scripts.backend_contract.infrastructure.field_mobile import DeviceOfflineVault, DeviceOfflineVaultRegistry


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
    inspection_schema = json.loads((ROOT / "schemas/inspection-session-v1.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(inspection_schema["$id"], Resource.from_contents(inspection_schema))
    Draft202012Validator(schema, format_checker=FormatChecker(), registry=registry).validate(package_mapping())
    registry = json.loads((ROOT / "config/schema-versions.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["schemas"] if item["schema"] == "offline-inspection-package-v1.schema.json")
    assert entry["future_version_policy"] == "FAIL_CLOSED"
    assert {"OFFLINE_INSPECTION", "FIELD_SYNC"} <= set(entry["consumers"])


def test_device_vault_encrypts_at_rest_reopens_offline_and_revocation_fails_closed(tmp_path: Path) -> None:
    package = offline_package_from_mapping(package_mapping())
    key = b"k" * 32
    vault = DeviceOfflineVault(tmp_path, key=key, device_id="DEVICE-001", workspace_id=WORKSPACE_ID)
    vault.save(package)
    stored = next(tmp_path.glob("*.offline"))
    assert b"PHOTO-001" not in stored.read_bytes()
    assert vault.load(package.package_id) == package

    reopened = DeviceOfflineVault(tmp_path, key=key, device_id="DEVICE-001", workspace_id=WORKSPACE_ID)
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
    vault = DeviceOfflineVault(tmp_path, key=b"m" * 32, device_id="DEVICE-001", workspace_id=WORKSPACE_ID)
    vault.save(package)
    vault.save_media(package.package_id, "PHOTO-001", original)
    assert vault.load_media(package.package_id, "PHOTO-001") == original
    media_file = next(tmp_path.glob("*.media"))
    assert original not in media_file.read_bytes()
    with pytest.raises(ValueError, match="hash|size|authority"):
        vault.save_media(package.package_id, "VIDEO-001", b"tampered")


def test_package_and_media_ciphertext_tamper_fail_closed(tmp_path: Path) -> None:
    original = b"synthetic original photo bytes"
    mapping = package_mapping()
    digest = hashlib.sha256(original).hexdigest()
    mapping["inspection_snapshot"]["photos"][0]["original_sha256"] = digest
    mapping["media_manifest"][0]["original_sha256"] = digest
    mapping["media_manifest"][0]["byte_size"] = len(original)
    package = offline_package_from_mapping(mapping)

    package_root = tmp_path / "package"
    package_vault = DeviceOfflineVault(package_root, key=b"t" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    package_vault.save(package)
    package_path = next(package_root.glob("*.offline"))
    tampered = bytearray(package_path.read_bytes())
    tampered[-1] ^= 1
    package_path.write_bytes(tampered)
    with pytest.raises(ValueError, match="integrity"):
        package_vault.load(package.package_id)

    media_root = tmp_path / "media"
    media_vault = DeviceOfflineVault(media_root, key=b"u" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    media_vault.save(package)
    media_vault.save_media(package.package_id, "PHOTO-001", original)
    media_path = next(media_root.glob("*.media"))
    tampered = bytearray(media_path.read_bytes())
    tampered[-1] ^= 1
    media_path.write_bytes(tampered)
    with pytest.raises(ValueError, match="integrity"):
        media_vault.load_media(package.package_id, "PHOTO-001")


def test_device_vault_concurrent_package_write_never_silently_overwrites(tmp_path: Path) -> None:
    package = offline_package_from_mapping(package_mapping())
    first = DeviceOfflineVault(tmp_path, key=b"r" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    second = DeviceOfflineVault(tmp_path, key=b"r" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    def save(vault):
        try:
            vault.save(package)
            return "saved"
        except FileExistsError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (first, second)))
    assert sorted(results) == ["conflict", "saved"]
    assert first.load(package.package_id) == package


def test_device_registry_revocation_is_device_wide_and_persistent(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    issued = registry.vault_for(WORKSPACE_ID, registry.device_id)
    registry.vault_for("22222222-2222-4222-8222-222222222222", registry.device_id)
    registry.revoke_device()
    with pytest.raises(PermissionError, match="revoked"):
        issued.load("ANY-PACKAGE")
    reopened = DeviceOfflineVaultRegistry(tmp_path)
    with pytest.raises(PermissionError, match="revoked"):
        reopened.vault_for(WORKSPACE_ID, registry.device_id)


def test_device_security_claim_is_explicitly_limited_to_threat_model_a(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    classification = registry.security_classification
    assert classification.threat_model == "A"
    assert classification.protects_plaintext_at_rest is True
    assert classification.protects_complete_tree_copy is False
    assert classification.protects_malicious_complete_tree_read_write is False
    assert (tmp_path / "offline-field-v1" / ".device-key").read_bytes() == registry._key


def test_revoked_device_can_be_replaced_without_reviving_old_identity(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    device_a = registry.device_id
    registry.revoke_device()

    revoked = DeviceOfflineVaultRegistry(tmp_path)
    with pytest.raises(PermissionError, match="revoked"):
        revoked.vault_for(WORKSPACE_ID, device_a)
    device_b = revoked.replace_revoked_device(device_a)
    assert device_b != device_a

    mapping = package_mapping()
    mapping["device_id"] = device_b
    package = offline_package_from_mapping(mapping)
    vault_b = revoked.vault_for(WORKSPACE_ID, device_b)
    vault_b.save(package)
    assert vault_b.load(package.package_id) == package
    with pytest.raises(PermissionError, match="authorized|revoked"):
        revoked.vault_for(WORKSPACE_ID, device_a)

    restarted = DeviceOfflineVaultRegistry(tmp_path)
    assert restarted.device_id == device_b
    assert restarted.vault_for(WORKSPACE_ID, device_b).load(package.package_id) == package
    with pytest.raises(PermissionError, match="authorized|revoked"):
        restarted.vault_for(WORKSPACE_ID, device_a)


def test_device_replacement_requires_revocation_and_exact_expected_identity(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    device_id = registry.device_id
    with pytest.raises(PermissionError, match="revoked"):
        registry.replace_revoked_device(device_id)
    registry.revoke_device()
    reopened = DeviceOfflineVaultRegistry(tmp_path)
    with pytest.raises(PermissionError, match="identity"):
        reopened.replace_revoked_device("DEVICE-WRONG")


def test_device_replacement_rolls_forward_after_crash_before_revocation_cleanup(tmp_path: Path, monkeypatch) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    old_device = registry.device_id
    registry.revoke_device()
    original_unlink = Path.unlink

    def fail_revocation_unlink(path, *args, **kwargs):
        if path.name == ".device-revoked":
            raise OSError("synthetic power loss")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_revocation_unlink)
    with pytest.raises(OSError, match="power loss"):
        registry.replace_revoked_device(old_device)
    monkeypatch.undo()

    recovered = DeviceOfflineVaultRegistry(tmp_path)
    assert recovered.device_id != old_device
    assert recovered.lifecycle_status == {"device_id": recovered.device_id, "generation": 2, "revoked": False}
    with pytest.raises(PermissionError, match="authorized"):
        recovered.vault_for(WORKSPACE_ID, old_device)


@pytest.mark.parametrize("failure_index", [1, 2, 3])
def test_device_replacement_rolls_forward_after_each_authority_replace(tmp_path: Path, monkeypatch, failure_index: int) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    old_device = registry.device_id
    registry.revoke_device()
    original_replace = os.replace
    calls = 0

    def fail_once(source, target):
        nonlocal calls
        calls += 1
        if calls == failure_index:
            raise OSError("synthetic replacement crash")
        return original_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_once)
    with pytest.raises(OSError, match="replacement crash"):
        registry.replace_revoked_device(old_device)
    monkeypatch.undo()

    recovered = DeviceOfflineVaultRegistry(tmp_path)
    assert recovered.device_id != old_device
    assert recovered.lifecycle_status["revoked"] is False


def test_concurrent_device_replacement_has_one_authoritative_winner(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    old_device = registry.device_id
    registry.revoke_device()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _replacement_outcome(registry, old_device), range(2)))

    winners = [value for value in outcomes if value.startswith("DEVICE-")]
    assert len(winners) == 1
    assert outcomes.count("DENIED") == 1
    assert DeviceOfflineVaultRegistry(tmp_path).device_id == winners[0]


def test_forged_replacement_journal_cannot_reactivate_revoked_device(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    old_device = registry.device_id
    registry.revoke_device()
    forged = {
        "old_device_id": old_device,
        "previous_generation": 1,
        "new_device_id": "DEVICE-" + "F" * 32,
        "new_generation": 2,
        "new_key_hex": "5a" * 32,
        "mac": "0" * 64,
    }
    registry._replacement_path(old_device).write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(PermissionError, match="intent is corrupt"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_stale_completed_journal_cannot_resurrect_later_revocation(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    device_a = registry.device_id
    registry.revoke_device()
    device_b = registry.replace_revoked_device(device_a)
    registry._replacement_path(device_a).with_suffix(".complete").unlink()
    registry.revoke_device()

    reopened = DeviceOfflineVaultRegistry(tmp_path)
    assert reopened.lifecycle_status == {"device_id": device_b, "generation": 2, "revoked": True}
    with pytest.raises(PermissionError, match="revoked"):
        reopened.vault_for(WORKSPACE_ID, device_b)


def test_partial_unpublished_replacement_intent_does_not_brick_revoked_lifecycle(tmp_path: Path, monkeypatch) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    old_device = registry.device_id
    registry.revoke_device()
    original = DeviceOfflineVaultRegistry._provision

    def partial(path, payload):
        if path.name.startswith(".replacement-intent."):
            path.write_bytes(payload[:7])
            raise OSError("synthetic partial journal crash")
        return original(path, payload)

    monkeypatch.setattr(DeviceOfflineVaultRegistry, "_provision", staticmethod(partial))
    with pytest.raises(OSError, match="partial journal"):
        registry.replace_revoked_device(old_device)
    monkeypatch.undo()

    reopened = DeviceOfflineVaultRegistry(tmp_path)
    assert reopened.lifecycle_status["revoked"] is True
    assert reopened.replace_revoked_device(old_device) != old_device


@pytest.mark.parametrize("target,payload", [
    (".lifecycle-key", None),
    (".lifecycle-key", b"Z" * 32),
    (".device-generation", b"999\n"),
    (".lifecycle-state", None),
])
def test_committed_lifecycle_authority_rejects_missing_or_substituted_state(tmp_path: Path, target: str, payload: bytes | None) -> None:
    DeviceOfflineVaultRegistry(tmp_path)
    path = tmp_path / "offline-field-v1" / target
    path.unlink()
    if payload is not None:
        path.write_bytes(payload)

    with pytest.raises(PermissionError, match="lifecycle|committed"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_legacy_generation_one_authority_migrates_and_reopens_existing_package(tmp_path: Path) -> None:
    root = tmp_path / "offline-field-v1"
    root.mkdir()
    key = b"L" * 32
    device_id = "DEVICE-" + "A" * 32
    (root / ".device-key").write_bytes(key)
    (root / ".device-id").write_text(device_id, encoding="ascii")
    package = offline_package_from_mapping({**package_mapping(), "device_id": device_id})
    legacy_vault = DeviceOfflineVault(
        root / hashlib.sha256(WORKSPACE_ID.encode("utf-8")).hexdigest(),
        key=key, device_id=device_id, workspace_id=WORKSPACE_ID,
    )
    legacy_vault.save(package)

    migrated = DeviceOfflineVaultRegistry(tmp_path)

    assert migrated.lifecycle_status == {"device_id": device_id, "generation": 1, "revoked": False}
    assert migrated.vault_for(WORKSPACE_ID, device_id).load(package.package_id) == package
    assert (root / ".lifecycle-migration-v1").exists()
    assert DeviceOfflineVaultRegistry(tmp_path).device_id == device_id
    migrated.revoke_device()
    replacement = migrated.replace_revoked_device(device_id)
    restarted = DeviceOfflineVaultRegistry(tmp_path)
    assert restarted.lifecycle_status == {"device_id": replacement, "generation": 2, "revoked": False}


def test_interrupted_legacy_lifecycle_migration_resumes_from_bound_record(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "offline-field-v1"
    root.mkdir()
    (root / ".device-key").write_bytes(b"L" * 32)
    (root / ".device-id").write_text("DEVICE-" + "A" * 32, encoding="ascii")
    original = DeviceOfflineVaultRegistry._provision

    def interrupt(path, payload):
        if path.name == ".lifecycle-key":
            raise OSError("synthetic migration interruption")
        return original(path, payload)

    monkeypatch.setattr(DeviceOfflineVaultRegistry, "_provision", staticmethod(interrupt))
    with pytest.raises(OSError, match="migration interruption"):
        DeviceOfflineVaultRegistry(tmp_path)
    monkeypatch.undo()

    recovered = DeviceOfflineVaultRegistry(tmp_path)
    assert recovered.lifecycle_status["generation"] == 1
    assert recovered.lifecycle_status["revoked"] is False


def test_completed_legacy_migration_record_cannot_be_replayed_after_authority_loss(tmp_path: Path) -> None:
    root = tmp_path / "offline-field-v1"
    root.mkdir()
    (root / ".device-key").write_bytes(b"L" * 32)
    (root / ".device-id").write_text("DEVICE-" + "A" * 32, encoding="ascii")
    DeviceOfflineVaultRegistry(tmp_path)
    assert (root / ".lifecycle-migration-v1.complete").exists()
    for name in (".lifecycle-state", ".lifecycle-key", ".device-generation"):
        (root / name).unlink()

    with pytest.raises(PermissionError, match="lifecycle"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_versioned_identity_prevents_completion_marker_rollback_from_reopening_migration(tmp_path: Path) -> None:
    root = tmp_path / "offline-field-v1"
    root.mkdir()
    (root / ".device-key").write_bytes(b"L" * 32)
    (root / ".device-id").write_text("DEVICE-" + "A" * 32, encoding="ascii")
    DeviceOfflineVaultRegistry(tmp_path)
    assert (root / ".device-id").read_text(encoding="ascii").startswith("V2\n")
    (root / ".lifecycle-migration-v1.complete").unlink()
    (root / ".lifecycle-state").unlink()

    with pytest.raises(PermissionError, match="committed lifecycle state is missing"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_versioned_identity_downgrade_is_rejected_by_committed_state(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    (tmp_path / "offline-field-v1" / ".device-id").write_text(registry.device_id, encoding="ascii")

    with pytest.raises(PermissionError, match="committed lifecycle state is corrupt"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_surviving_offline_data_prevents_pristine_reprovision_after_authority_loss(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    package = offline_package_from_mapping({**package_mapping(), "device_id": registry.device_id})
    registry.vault_for(WORKSPACE_ID, registry.device_id).save(package)
    root = tmp_path / "offline-field-v1"
    for name in (".device-key", ".device-id", ".device-generation", ".lifecycle-key", ".lifecycle-state"):
        (root / name).unlink()

    with pytest.raises(PermissionError, match="lifecycle authority is incomplete"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_interrupted_legacy_migration_rejects_provisional_generation_substitution(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "offline-field-v1"
    root.mkdir()
    (root / ".device-key").write_bytes(b"L" * 32)
    (root / ".device-id").write_text("DEVICE-" + "A" * 32, encoding="ascii")
    original = DeviceOfflineVaultRegistry._provision

    def interrupt(path, payload):
        if path.name == ".lifecycle-state":
            raise OSError("synthetic state interruption")
        return original(path, payload)

    monkeypatch.setattr(DeviceOfflineVaultRegistry, "_provision", staticmethod(interrupt))
    with pytest.raises(OSError, match="state interruption"):
        DeviceOfflineVaultRegistry(tmp_path)
    monkeypatch.undo()
    (root / ".device-generation").write_text("999\n", encoding="ascii")

    with pytest.raises(PermissionError, match="migration authority is corrupt"):
        DeviceOfflineVaultRegistry(tmp_path)


def _replacement_outcome(registry: DeviceOfflineVaultRegistry, expected_device_id: str) -> str:
    try:
        return registry.replace_revoked_device(expected_device_id)
    except (FileExistsError, PermissionError):
        return "DENIED"


def test_workspace_backup_readiness_fails_closed_while_offline_work_is_pending(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    package = offline_package_from_mapping({**package_mapping(), "device_id": registry.device_id})
    vault = registry.vault_for(WORKSPACE_ID, registry.device_id)
    vault.save(package)

    with pytest.raises(ValueError, match="pending offline field work must be synchronized before backup"):
        registry.assert_workspace_backup_ready(WORKSPACE_ID)

    vault.record_accepted_sync(package)
    registry.assert_workspace_backup_ready(WORKSPACE_ID)


def test_device_revocation_survives_marker_deletion_for_live_and_reopened_authority(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    device_id = registry.device_id
    issued = registry.vault_for(WORKSPACE_ID, device_id)
    registry.revoke_device()
    (tmp_path / "offline-field-v1" / ".device-revoked").unlink()
    with pytest.raises(PermissionError, match="revoked"):
        registry.vault_for(WORKSPACE_ID, device_id)
    with pytest.raises(PermissionError, match="revoked"):
        issued.load("ANY-PACKAGE")
    with pytest.raises(PermissionError, match="revoked"):
        DeviceOfflineVaultRegistry(tmp_path)


def test_device_registry_root_replacement_cannot_bypass_revocation(tmp_path: Path) -> None:
    registry = DeviceOfflineVaultRegistry(tmp_path)
    device_id = registry.device_id
    registry.revoke_device()
    root = tmp_path / "offline-field-v1"
    root.rename(tmp_path / "retired-registry")
    root.mkdir()
    with pytest.raises(PermissionError, match="identity"):
        registry.vault_for(WORKSPACE_ID, device_id)


def test_device_vault_revalidates_root_identity_on_every_operation(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    vault = DeviceOfflineVault(root, key=b"i" * 32, device_id="DEVICE-001", workspace_id=WORKSPACE_ID)
    root.rename(tmp_path / "retired-vault")
    root.mkdir()
    with pytest.raises(PermissionError, match="identity"):
        vault.save(offline_package_from_mapping(package_mapping()))


def test_forged_receipt_cannot_hide_pending_offline_capture(tmp_path: Path) -> None:
    package = offline_package_from_mapping(package_mapping())
    vault = DeviceOfflineVault(tmp_path, key=b"f" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)
    session_hash = hashlib.sha256(package.device_session_id.encode("utf-8")).hexdigest()
    (tmp_path / f"{session_hash}.999.receipt").write_bytes(b"forged")
    inventory = vault.inventory_pending_packages()
    assert [item.package_id for item in inventory.items] == [package.package_id]
    assert "CORRUPT_OFFLINE_AUTHORITY" in {item.code for item in inventory.conflicts}


def test_pending_inventory_keeps_valid_capture_visible_beside_corrupt_sibling(tmp_path: Path) -> None:
    package = offline_package_from_mapping(package_mapping())
    vault = DeviceOfflineVault(tmp_path, key=b"q" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)
    (tmp_path / "corrupt.offline").write_bytes(b"truncated")

    inventory = vault.inventory_pending_packages()

    assert [item.package_id for item in inventory.items] == [package.package_id]
    assert {item.code for item in inventory.conflicts} == {"CORRUPT_OFFLINE_PACKAGE", "CORRUPT_OFFLINE_MEDIA"}


def test_pending_inventory_keeps_package_visible_and_reports_corrupt_media(tmp_path: Path) -> None:
    original = b"photo-original"
    mapping = package_mapping()
    mapping["media_manifest"] = [mapping["media_manifest"][0]]
    mapping["media_manifest"][0]["original_sha256"] = hashlib.sha256(original).hexdigest()
    mapping["media_manifest"][0]["byte_size"] = len(original)
    mapping["inspection_snapshot"]["photos"][0]["original_sha256"] = hashlib.sha256(original).hexdigest()
    mapping["inspection_snapshot"]["videos"] = []
    mapping["inspection_snapshot"]["sketches"] = []
    package = offline_package_from_mapping(mapping)
    vault = DeviceOfflineVault(tmp_path, key=b"m" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)
    vault.save_media(package.package_id, "PHOTO-001", original)
    media_path = vault._media_path(package.package_id, "PHOTO-001")
    payload = bytearray(media_path.read_bytes())
    payload[-1] ^= 1
    media_path.write_bytes(payload)

    inventory = vault.inventory_pending_packages()

    assert [item.package_id for item in inventory.items] == [package.package_id]
    assert "CORRUPT_OFFLINE_MEDIA" in {item.code for item in inventory.conflicts}


def test_revocation_linearizes_after_complete_package_read(tmp_path: Path, monkeypatch) -> None:
    package = offline_package_from_mapping(package_mapping())
    vault = DeviceOfflineVault(tmp_path, key=b"l" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)
    decoding = Event()
    release = Event()
    original_decode = DeviceOfflineVault._decode_package

    def delayed_decode(self, payload, key):
        decoding.set()
        assert release.wait(timeout=5)
        return original_decode(self, payload, key)

    monkeypatch.setattr(DeviceOfflineVault, "_decode_package", delayed_decode)
    with ThreadPoolExecutor(max_workers=2) as pool:
        loading = pool.submit(vault.load, package.package_id)
        assert decoding.wait(timeout=5)
        revoking = pool.submit(vault.revoke)
        assert not revoking.done()
        release.set()
        assert loading.result(timeout=5) == package
        revoking.result(timeout=5)
    with pytest.raises(PermissionError, match="revoked"):
        vault.load(package.package_id)


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ({"workspace_id": "22222222-2222-4222-8222-222222222222"}, "WORKSPACE_MISMATCH"),
        ({"inspection_id": "OTHER-INSPECTION"}, "INSPECTION_MISMATCH"),
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
        device_id=package.device_id,
        device_session_id=package.device_session_id,
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
        device_id=package.device_id,
        device_session_id=package.device_session_id,
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


def test_sync_rejects_device_or_session_swap_and_unverified_media() -> None:
    package = offline_package_from_mapping(package_mapping())
    common = dict(
        workspace_id=package.workspace_id, inspection_id=package.inspection_id,
        device_id=package.device_id, device_session_id=package.device_session_id,
        current_inspection_revision=package.inspection_revision,
        planning_revision=package.planning_revision, source_revision=package.source_revision,
        last_device_sequence=0, deleted_record_ids=(), known_media_hashes=(),
        media_authority_verified=True,
    )
    for change, code in (({"device_id": "OTHER"}, "DEVICE_MISMATCH"), ({"device_session_id": "OTHER"}, "DEVICE_SESSION_MISMATCH"), ({"media_authority_verified": False}, "MEDIA_AUTHORITY_UNVERIFIED")):
        decision = adjudicate_offline_sync(package, SyncAuthority(**{**common, **change}))
        assert decision.accepted is False
        assert code in {item.code for item in decision.conflicts}


def test_offline_update_rejects_foreign_workspace_media_even_with_identical_hash(tmp_path: Path) -> None:
    originals = {"PHOTO-001": b"photo", "VIDEO-001": b"video", "SKETCH-001": b"sketch"}
    mapping = package_mapping()
    for manifest, collection in zip(mapping["media_manifest"], ("photos", "videos", "sketches")):
        original = originals[manifest["record_id"]]
        digest = hashlib.sha256(original).hexdigest()
        manifest["original_sha256"] = digest
        manifest["byte_size"] = len(original)
        mapping["inspection_snapshot"][collection][0]["original_sha256"] = digest
    package = offline_package_from_mapping(mapping)
    vault = DeviceOfflineVault(tmp_path, key=b"w" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)

    class ForeignPrivate:
        def execute(self, _workspace_id, content_id):
            manifest = next(item for item in package.media_manifest if item.private_content_id == str(content_id))
            original = originals[manifest.record_id]
            return SimpleNamespace(
                metadata=SimpleNamespace(
                    workspace_id="22222222-2222-4222-8222-222222222222",
                    checksum_sha256=manifest.original_sha256,
                    byte_size=len(original),
                    media_type=manifest.media_type,
                ),
                content=original,
            )

    updater = UpdateOfflineInspection(
        ForeignPrivate(),
        lambda *_: vault,
        SimpleNamespace(now=lambda: __import__("datetime").datetime.fromisoformat("2026-08-31T15:00:00+00:00")),
        SimpleNamespace(new_uuid=lambda: UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")),
    )
    with pytest.raises(ValueError, match="revision conflict"):
        updater.execute(
            WORKSPACE_ID,
            device_id=package.device_id,
            package_id=package.package_id,
            expected_package_revision=2,
            snapshot=package.inspection_snapshot,
        )
    with pytest.raises(ValueError, match="workspace"):
        updater.execute(
            WORKSPACE_ID,
            device_id=package.device_id,
            package_id=package.package_id,
            expected_package_revision=1,
            snapshot=package.inspection_snapshot,
        )


def test_field_mobile_boundary_has_no_remote_egress_client_or_absolute_frontend_url() -> None:
    backend = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "scripts/backend_contract/field_mobile.py",
            "scripts/backend_contract/application/field_mobile.py",
            "scripts/backend_contract/infrastructure/field_mobile.py",
        )
    )
    frontend = (ROOT / "frontend/src/data/fieldMobile.ts").read_text(encoding="utf-8")
    assert not any(token in backend for token in ("import requests", "import httpx", "urllib.request", "socket."))
    assert "http://" not in frontend and "https://" not in frontend and "//server" not in frontend
    assert "`/app-api/v1/workspaces/${workspaceId}/" in frontend


def test_offline_update_sync_and_durable_replay_receipt_form_one_vertical(tmp_path: Path) -> None:
    originals = {"PHOTO-001": b"photo-original", "VIDEO-001": b"video-original", "SKETCH-001": b"sketch-original"}
    mapping = package_mapping()
    for manifest, collection in zip(mapping["media_manifest"], ("photos", "videos", "sketches")):
        original = originals[manifest["record_id"]]
        digest = hashlib.sha256(original).hexdigest()
        manifest["original_sha256"] = digest
        manifest["byte_size"] = len(original)
        mapping["inspection_snapshot"][collection][0]["original_sha256"] = digest
    package = offline_package_from_mapping(mapping)
    vault = DeviceOfflineVault(tmp_path, key=b"z" * 32, device_id=package.device_id, workspace_id=package.workspace_id)

    by_content = {item.private_content_id: originals[item.record_id] for item in package.media_manifest}
    class Private:
        def execute(self, _workspace_id, content_id):
            original = by_content[str(content_id)]
            manifest = next(item for item in package.media_manifest if item.private_content_id == str(content_id))
            return SimpleNamespace(metadata=SimpleNamespace(workspace_id=WORKSPACE_ID, checksum_sha256=manifest.original_sha256, byte_size=len(original), media_type=manifest.media_type), content=original)
    generated = iter((UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"), UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")))
    ids = SimpleNamespace(new_uuid=lambda: next(generated))
    clock = SimpleNamespace(now=lambda: __import__("datetime").datetime.fromisoformat("2026-08-31T15:00:00+00:00"))
    getter = SimpleNamespace(execute=lambda _workspace: (SimpleNamespace(revision=package.inspection_revision), package.inspection_snapshot))
    prepared = PrepareOfflineInspection(getter, Private(), lambda *_: vault, clock, ids).execute(
        WORKSPACE_ID, device_id=package.device_id, device_session_id=package.device_session_id,
    )
    assert vault.verify_media_authority(prepared.package_id)
    assert vault.list_pending_packages()[0].package_id == prepared.package_id

    package = prepared
    updater = UpdateOfflineInspection(Private(), lambda *_: vault, clock, ids)
    updated = updater.execute(WORKSPACE_ID, device_id=package.device_id, package_id=package.package_id, expected_package_revision=1, snapshot=package.inspection_snapshot)
    assert updated.package_revision == 2
    assert vault.verify_media_authority(updated.package_id)
    assert [item.package_id for item in vault.list_pending_packages()] == [updated.package_id]

    superseded, record = SyncOfflineInspection(getter, SimpleNamespace(), lambda *_: vault).execute(
        WORKSPACE_ID, device_id=package.device_id, package_id=package.package_id,
    )
    assert record is None
    assert "SUPERSEDED_PACKAGE" in {item.code for item in superseded.conflicts}

    current = SimpleNamespace(revision=package.inspection_revision)
    getter = SimpleNamespace(execute=lambda _workspace: (current, package.inspection_snapshot))
    saved = SimpleNamespace(revision=package.inspection_revision + 1)
    saver = SimpleNamespace(execute=lambda *_args: saved)
    sync = SyncOfflineInspection(getter, saver, lambda *_: vault)
    decision, record = sync.execute(WORKSPACE_ID, device_id=package.device_id, package_id=updated.package_id)
    assert decision.accepted and record is saved
    assert vault.list_pending_packages() == ()
    replay, record = sync.execute(WORKSPACE_ID, device_id=package.device_id, package_id=updated.package_id)
    assert replay.accepted and record is current


def test_sync_recovers_exact_canonical_save_after_receipt_write_failure(tmp_path: Path, monkeypatch) -> None:
    originals = {"PHOTO-001": b"photo", "VIDEO-001": b"video", "SKETCH-001": b"sketch"}
    mapping = package_mapping()
    for manifest, collection in zip(mapping["media_manifest"], ("photos", "videos", "sketches")):
        original = originals[manifest["record_id"]]
        digest = hashlib.sha256(original).hexdigest()
        manifest["original_sha256"] = digest
        manifest["byte_size"] = len(original)
        mapping["inspection_snapshot"][collection][0]["original_sha256"] = digest
    package = offline_package_from_mapping(mapping)
    vault = DeviceOfflineVault(tmp_path, key=b"j" * 32, device_id=package.device_id, workspace_id=package.workspace_id)
    vault.save(package)
    for item in package.media_manifest:
        vault.save_media(package.package_id, item.record_id, originals[item.record_id])

    state = {"revision": package.inspection_revision, "snapshot": package.inspection_snapshot, "writes": 0}

    class Getter:
        def execute(self, _workspace_id):
            return SimpleNamespace(revision=state["revision"]), state["snapshot"]

    class Saver:
        def execute(self, _workspace_id, snapshot, expected_revision):
            assert expected_revision == state["revision"]
            state["revision"] += 1
            state["snapshot"] = snapshot
            state["writes"] += 1
            return SimpleNamespace(revision=state["revision"])

    original_receipt = vault.record_accepted_sync
    attempts = 0

    def fail_once(value):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("synthetic receipt failure")
        return original_receipt(value)

    monkeypatch.setattr(vault, "record_accepted_sync", fail_once)
    service = SyncOfflineInspection(Getter(), Saver(), lambda *_: vault)
    with pytest.raises(OSError, match="receipt"):
        service.execute(WORKSPACE_ID, device_id=package.device_id, package_id=package.package_id)
    assert state["writes"] == 1

    recovered, record = service.execute(WORKSPACE_ID, device_id=package.device_id, package_id=package.package_id)
    assert recovered.accepted is True
    assert record.revision == state["revision"]
    assert state["writes"] == 1
    assert vault.list_pending_packages() == ()

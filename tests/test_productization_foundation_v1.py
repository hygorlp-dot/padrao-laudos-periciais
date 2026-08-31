from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts.backend_contract.application.content import OpenPrivateContent
from scripts.backend_contract.application.models import (
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import RepositoryConflict, RepositoryIntegrityError
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
from scripts.backend_contract.productization import (
    ARTIFACT_COMPATIBILITY,
    CreateWorkspaceBackup,
    PRODUCT_RELEASE_VERSION,
    RestoreWorkspaceBackup,
    STORAGE_FORMAT_VERSION,
    VerifyWorkspaceBackup,
    collect_support_diagnostics,
    migrate_backup_mapping,
    workspace_backup_from_mapping,
    workspace_backup_to_mapping,
)


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"


def backup_mapping(version: int = 1) -> dict:
    value = {
        "schema_version": "1.0.0",
        "format_version": version,
        "product_release": PRODUCT_RELEASE_VERSION,
        "storage_schema_version": 1,
        "workspace": {
            "workspace_id": WORKSPACE_ID,
            "name": "Perícia sintética",
            "created_at": "2026-08-31T12:00:00+00:00",
        },
        "artifact_revisions": [],
        "private_contents": [],
        "member_hashes": {},
        "manifest_sha256": "0" * 64,
        "created_at": "2026-08-31T13:00:00+00:00",
    }
    return value


def test_backup_v1_round_trip_is_exact_and_supported_window_is_finite() -> None:
    payload = backup_mapping()
    value = workspace_backup_from_mapping(payload)
    assert value.format_version == STORAGE_FORMAT_VERSION == 1
    assert workspace_backup_to_mapping(value) == payload


def test_v0_migration_is_deterministic_preserves_history_and_v1_is_idempotent() -> None:
    legacy = backup_mapping(0)
    legacy.pop("member_hashes")
    legacy.pop("manifest_sha256")
    legacy.pop("schema_version")
    legacy["artifact_revisions"] = [{"payload": {"source_provenance": "immutable"}, "checksum_sha256": "a" * 64}]
    first = migrate_backup_mapping(legacy)
    second = migrate_backup_mapping(deepcopy(legacy))
    assert first == second
    assert first["format_version"] == 1
    assert first["artifact_revisions"] == legacy["artifact_revisions"]
    assert migrate_backup_mapping(first) == first


@pytest.mark.parametrize("version", (-1, 2, 999))
def test_unknown_or_expired_backup_version_fails_closed(version: int) -> None:
    with pytest.raises(ValueError, match="version"):
        migrate_backup_mapping(backup_mapping(version))


def test_product_release_compatibility_window_is_exact_not_open_ended() -> None:
    payload = backup_mapping()
    payload["product_release"] = "0.99.0"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(RepositoryIntegrityError, match="compatibility"):
        VerifyWorkspaceBackup().execute(raw)


def test_backup_contract_rejects_unknown_fields() -> None:
    payload = backup_mapping()
    payload["reinterpret_history"] = True
    with pytest.raises(ValueError, match="fields"):
        workspace_backup_from_mapping(payload)


def test_every_portable_material_artifact_has_an_explicit_finite_strategy() -> None:
    expected = {"BUDGET_SNAPSHOT_V1", "CASE_ANALYSIS_SNAPSHOT_V1", "DELIVERY_SNAPSHOT_V1", "EXPERT_MASTER_PROFILE_V1", "INSPECTION_SESSION_V1", "PERICIAL_PLANNING_SNAPSHOT_V1", "PROCESS_CASE", "REPORT_SNAPSHOT_V1", "TECHNICAL_SNAPSHOT_V1"}
    assert set(ARTIFACT_COMPATIBILITY) == expected
    assert all(item == {"current_version": "1.0.0", "supported_versions": ("1.0.0",), "migration": None, "future_version_policy": "FAIL_CLOSED"} for item in ARTIFACT_COMPATIBILITY.values())


class Clock:
    def now(self): return datetime.fromisoformat("2026-08-31T13:00:00+00:00")


class PrivateStore:
    def __init__(self): self.items: dict[str, PrivateContent] = {}
    def list_all(self, workspace_id): return tuple(item.metadata for item in self.items.values() if item.metadata.workspace_id == workspace_id)
    def open_content(self, workspace_id, content_id):
        item = self.items[str(content_id)]
        assert item.metadata.workspace_id == workspace_id
        stream = io.BytesIO(item.content)
        return OpenPrivateContent(item.metadata, stream, stream.close)
    def store(self, metadata, content): self.items[str(metadata.content_id)] = PrivateContent(metadata, content); return metadata
    def snapshot(self): return dict(self.items)
    def restore(self, snapshot): self.items = dict(snapshot)


def seeded_store(path: Path, private: PrivateStore) -> tuple[SQLiteApplicationStore, WorkspaceId]:
    workspace_id = WorkspaceId.parse(WORKSPACE_ID)
    store = SQLiteApplicationStore(path)
    store.workspaces.create(PericiaWorkspace(workspace_id, "Perícia sintética", "2026-08-31T12:00:00+00:00"))
    payload = json.loads((Path(__file__).parent / "fixtures/budget-snapshot-v1.json").read_text(encoding="utf-8"))
    store.revisions.append(workspace_id=workspace_id, artifact_kind="BUDGET_SNAPSHOT_V1", artifact_id="BUDGET-SNAPSHOT", revision_id="22222222-2222-4222-8222-222222222222", created_at="2026-08-31T12:10:00+00:00", payload=payload)
    content = b"synthetic-private-content"
    metadata = PrivateContentMetadata(workspace_id, PrivateContentId.parse("33333333-3333-4333-8333-333333333333"), "synthetic.pdf", len(content), hashlib.sha256(content).hexdigest(), "application/pdf", "2026-08-31T12:20:00+00:00", PrivateContentOrigin.LOCAL_IMPORT)
    private.store(metadata, content)
    return store, workspace_id


def test_backup_restore_reopen_preserves_exact_history_private_bytes_and_provenance(tmp_path) -> None:
    source_private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", source_private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, source_private, Clock()).execute(workspace_id)
    assert package == CreateWorkspaceBackup(source.workspaces, source.revisions, source_private, Clock()).execute(workspace_id)
    verified = VerifyWorkspaceBackup().execute(package)
    assert verified.workspace.workspace_id == WORKSPACE_ID
    target_private = PrivateStore(); target = SQLiteApplicationStore(tmp_path / "staging.db")
    receipt = RestoreWorkspaceBackup(target.workspaces, target.revisions, target_private, (target, target_private)).execute(package)
    assert receipt.artifact_revisions == receipt.private_contents == 1
    assert target.revisions.list_workspace(workspace_id) == source.revisions.list_workspace(workspace_id)
    assert target_private.items == source_private.items
    source.close(); target.close()


def test_corruption_and_foreign_workspace_fail_closed_before_restore_mutation(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    tampered = json.loads(package)
    tampered["artifact_revisions"][0]["payload"]["status"] = "DRAFT"
    corrupt = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
    target = SQLiteApplicationStore(tmp_path / "staging.db")
    target_private = PrivateStore()
    with pytest.raises(RepositoryIntegrityError): RestoreWorkspaceBackup(target.workspaces, target.revisions, target_private, (target, target_private)).execute(corrupt)
    assert target.workspaces.list_all() == ()
    assert collect_support_diagnostics(corrupt).error_code == "BACKUP_INTEGRITY_INVALID"
    source.close(); target.close()


def test_resealed_inner_corruption_still_fails_domain_and_private_validation(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)

    def reseal(mapping: dict) -> bytes:
        def canonical(value: object) -> bytes:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        mapping["member_hashes"] = {
            "artifact_revisions": hashlib.sha256(canonical(mapping["artifact_revisions"])).hexdigest(),
            "private_contents": hashlib.sha256(canonical(mapping["private_contents"])).hexdigest(),
        }
        mapping["manifest_sha256"] = hashlib.sha256(canonical({key: value for key, value in mapping.items() if key != "manifest_sha256"})).hexdigest()
        return canonical(mapping)

    forged_revision = json.loads(package)
    forged_revision["artifact_revisions"][0]["checksum_sha256"] = "0" * 64
    with pytest.raises(RepositoryIntegrityError, match="checksum"):
        VerifyWorkspaceBackup().execute(reseal(forged_revision))

    forged_private = json.loads(package)
    forged_private["private_contents"][0]["content_base64"] = "Zm9yZ2Vk"
    with pytest.raises(RepositoryIntegrityError, match="private"):
        VerifyWorkspaceBackup().execute(reseal(forged_private))
    source.close()


def test_duplicate_private_identity_and_failed_store_roll_back_all_staging_state(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    duplicated = json.loads(package)
    duplicated["private_contents"].append(deepcopy(duplicated["private_contents"][0]))
    def canonical(value: object) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    duplicated["member_hashes"]["private_contents"] = hashlib.sha256(canonical(duplicated["private_contents"])).hexdigest()
    duplicated["manifest_sha256"] = hashlib.sha256(canonical({key: value for key, value in duplicated.items() if key != "manifest_sha256"})).hexdigest()
    with pytest.raises(RepositoryIntegrityError, match="duplicated"):
        VerifyWorkspaceBackup().execute(canonical(duplicated))

    class FailingPrivate(PrivateStore):
        def store(self, _metadata, _content): raise OSError("synthetic private failure")
    target = SQLiteApplicationStore(tmp_path / "staging.db"); failing = FailingPrivate()
    with pytest.raises(OSError, match="synthetic"):
        RestoreWorkspaceBackup(target.workspaces, target.revisions, failing, (target, failing)).execute(package)
    assert target.workspaces.list_all() == ()
    assert target.revisions.list_workspace(workspace_id) == ()
    assert failing.items == {}
    source.close(); target.close()


def test_restore_refuses_nonempty_target_as_rollback_boundary(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    with pytest.raises(RepositoryConflict): RestoreWorkspaceBackup(source.workspaces, source.revisions, private, (source, private)).execute(package)
    assert len(source.revisions.list_workspace(workspace_id)) == 1
    source.close()


def test_restore_requires_globally_empty_staging_not_only_absent_source_id(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    target = SQLiteApplicationStore(tmp_path / "staging.db")
    target.workspaces.create(PericiaWorkspace(WorkspaceId.parse("44444444-4444-4444-8444-444444444444"), "Outro", "2026-08-31T12:00:00+00:00"))
    target_private = PrivateStore()
    with pytest.raises(RepositoryConflict, match="empty"):
        RestoreWorkspaceBackup(target.workspaces, target.revisions, target_private, (target, target_private)).execute(package)
    assert len(target.workspaces.list_all()) == 1
    source.close(); target.close()


def test_support_diagnostics_are_sanitized_and_never_egress_private_data(tmp_path) -> None:
    private = PrivateStore(); source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    diagnostic = collect_support_diagnostics(package)
    rendered = repr(diagnostic)
    assert diagnostic.integrity_status == "PASS" and diagnostic.private_egress is False
    assert "synthetic.pdf" not in rendered and WORKSPACE_ID not in rendered and "private-content" not in rendered
    source.close()

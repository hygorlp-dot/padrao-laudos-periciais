from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
import os
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
from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore
from scripts.backend_contract.local_api.composition import build_local_api
from scripts.backend_contract.productization import (
    ARTIFACT_COMPATIBILITY,
    CreateWorkspaceBackup,
    PRODUCT_RELEASE_VERSION,
    RecoveryStaging,
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
    expected = {
        "BUDGET_SNAPSHOT_V1",
        "CASE_ANALYSIS_SNAPSHOT_V1",
        "DELIVERY_SNAPSHOT_V1",
        "EXPERT_MASTER_PROFILE_V1",
        "INSPECTION_SESSION_V1",
        "PERICIAL_PLANNING_SNAPSHOT_V1",
        "PROCESS_CASE",
        "REPORT_SNAPSHOT_V1",
        "TECHNICAL_SNAPSHOT_V1",
    }
    assert set(ARTIFACT_COMPATIBILITY) == expected
    assert all(item == {"current_version": "1.0.0", "supported_versions": ("1.0.0",), "migration": None, "future_version_policy": "FAIL_CLOSED"} for item in ARTIFACT_COMPATIBILITY.values())


class Clock:
    def now(self):
        return datetime.fromisoformat("2026-08-31T13:00:00+00:00")


class PrivateStore:
    def __init__(self):
        self.items: dict[str, PrivateContent] = {}

    def list_all(self, workspace_id):
        return tuple(item.metadata for item in self.items.values() if item.metadata.workspace_id == workspace_id)

    def open_content(self, workspace_id, content_id):
        item = self.items[str(content_id)]
        assert item.metadata.workspace_id == workspace_id
        stream = io.BytesIO(item.content)
        return OpenPrivateContent(item.metadata, stream, stream.close)

    def store(self, metadata, content):
        self.items[str(metadata.content_id)] = PrivateContent(metadata, content)
        return metadata

    def snapshot(self):
        return dict(self.items)

    def restore(self, snapshot):
        self.items = dict(snapshot)


def seeded_store(path: Path, private: PrivateStore) -> tuple[SQLiteApplicationStore, WorkspaceId]:
    workspace_id = WorkspaceId.parse(WORKSPACE_ID)
    store = SQLiteApplicationStore(path)
    store.workspaces.create(PericiaWorkspace(workspace_id, "Perícia sintética", "2026-08-31T12:00:00+00:00"))
    payload = json.loads((Path(__file__).parent / "fixtures/budget-snapshot-v1.json").read_text(encoding="utf-8"))
    store.revisions.append(
        workspace_id=workspace_id,
        artifact_kind="BUDGET_SNAPSHOT_V1",
        artifact_id="BUDGET-SNAPSHOT",
        revision_id="22222222-2222-4222-8222-222222222222",
        created_at="2026-08-31T12:10:00+00:00",
        payload=payload,
    )
    content = b"synthetic-private-content"
    metadata = PrivateContentMetadata(
        workspace_id,
        PrivateContentId.parse("33333333-3333-4333-8333-333333333333"),
        "synthetic.pdf",
        len(content),
        hashlib.sha256(content).hexdigest(),
        "application/pdf",
        "2026-08-31T12:20:00+00:00",
        PrivateContentOrigin.LOCAL_IMPORT,
    )
    private.store(metadata, content)
    return store, workspace_id


def test_backup_restore_reopen_preserves_exact_history_private_bytes_and_provenance(tmp_path) -> None:
    source_private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", source_private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, source_private, Clock()).execute(workspace_id)
    assert package == CreateWorkspaceBackup(source.workspaces, source.revisions, source_private, Clock()).execute(workspace_id)
    verified = VerifyWorkspaceBackup().execute(package)
    assert verified.workspace.workspace_id == WORKSPACE_ID
    staging = RecoveryStaging.create(tmp_path / "staging")
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    assert receipt.artifact_revisions == receipt.private_contents == 1
    assert staging.revisions.list_workspace(workspace_id) == source.revisions.list_workspace(workspace_id)
    with staging.private_contents.open_content(workspace_id, PrivateContentId.parse("33333333-3333-4333-8333-333333333333")) as opened:
        assert opened.stream.read() == b"synthetic-private-content"
    source.close()
    staging.close()


def test_restore_without_private_members_uses_same_owned_recovery_boundary(tmp_path) -> None:
    source_private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", source_private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, None, Clock()).execute(workspace_id)
    staging = RecoveryStaging.create(tmp_path / "staging")
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    assert receipt.private_contents == 0 and len(staging.revisions.list_workspace(workspace_id)) == 1
    source.close()
    staging.close()


def test_corruption_and_foreign_workspace_fail_closed_before_restore_mutation(tmp_path) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    tampered = json.loads(package)
    tampered["artifact_revisions"][0]["payload"]["status"] = "DRAFT"
    corrupt = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
    staging_root = tmp_path / "staging"
    staging = RecoveryStaging.create(staging_root)
    with pytest.raises(RepositoryIntegrityError):
        RestoreWorkspaceBackup(staging).execute(corrupt)
    assert staging.discarded is True and staging_root.exists()
    assert collect_support_diagnostics(corrupt).error_code == "BACKUP_INTEGRITY_INVALID"
    source.close()


def test_resealed_inner_corruption_still_fails_domain_and_private_validation(tmp_path) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
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


def test_duplicate_private_identity_and_failed_store_discard_owned_staging(tmp_path, monkeypatch) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    duplicated = json.loads(package)
    duplicated["private_contents"].append(deepcopy(duplicated["private_contents"][0]))

    def canonical(value: object) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    duplicated["member_hashes"]["private_contents"] = hashlib.sha256(canonical(duplicated["private_contents"])).hexdigest()
    duplicated["manifest_sha256"] = hashlib.sha256(canonical({key: value for key, value in duplicated.items() if key != "manifest_sha256"})).hexdigest()
    with pytest.raises(RepositoryIntegrityError, match="duplicated"):
        VerifyWorkspaceBackup().execute(canonical(duplicated))

    staging_root = tmp_path / "staging"
    staging = RecoveryStaging.create(staging_root)

    def fail_store(self, _metadata, _content):
        raise OSError("synthetic private failure")

    monkeypatch.setattr(LocalPrivateContentStore, "store", fail_store)
    with pytest.raises(OSError, match="synthetic"):
        RestoreWorkspaceBackup(staging).execute(package)
    assert staging.discarded is True and staging_root.exists()
    assert len(source.revisions.list_workspace(workspace_id)) == 1
    source.close()


def test_restore_refuses_nonempty_target_as_rollback_boundary(tmp_path) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    with pytest.raises(TypeError):
        RestoreWorkspaceBackup(source).execute(package)
    assert len(source.revisions.list_workspace(workspace_id)) == 1
    source.close()


def test_recovery_staging_cannot_be_composed_around_active_storage(tmp_path) -> None:
    active_root = tmp_path / "active"
    active_root.mkdir()
    active = SQLiteApplicationStore(active_root / "workspace.sqlite3")
    private = LocalPrivateContentStore.open_or_provision(active_root / "private")
    with pytest.raises(TypeError, match="must be created"):
        RecoveryStaging(active_root, active, private, os.lstat(active_root))
    assert active_root.exists()
    private.close()
    active.close()


def test_recovery_staging_repositories_cannot_be_redirected(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    unrelated = SQLiteApplicationStore(tmp_path / "unrelated.db")
    with pytest.raises(AttributeError):
        staging.workspaces = unrelated.workspaces
    with pytest.raises(AttributeError):
        staging.database = unrelated
    assert staging.workspaces is staging.database.workspaces
    staging.close()
    unrelated.close()


def test_recovery_staging_authority_rejects_internal_resource_substitution(tmp_path) -> None:
    source_private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", source_private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, source_private, Clock()).execute(workspace_id)
    staging = RecoveryStaging.create(tmp_path / "staging")
    owned_database = staging.database
    active_root = tmp_path / "active"
    active_root.mkdir()
    active = SQLiteApplicationStore(active_root / "workspace.sqlite3")
    active_private = LocalPrivateContentStore.open_or_provision(active_root / "private")
    staging._database = active
    staging._private_contents = active_private
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    assert receipt.workspace_id == WORKSPACE_ID
    assert active.workspaces.list_all() == ()
    assert len(owned_database.workspaces.list_all()) == 1
    active_private.close()
    active.close()
    staging.close()
    source.close()


def test_recovery_staging_is_restrictive_and_durably_not_promotable(tmp_path) -> None:
    root = tmp_path / "staging"
    staging = RecoveryStaging.create(root)
    marker = root / "RECOVERY_NOT_PROMOTABLE"
    assert marker.read_bytes() == b"RECOVERY_STAGING_V1\n"
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert marker.stat().st_mode & 0o777 == 0o600
    staging.discard()
    assert marker.read_bytes() == b"RECOVERY_STAGING_V1\n"


def test_recovery_quarantine_marker_handles_partial_writes(tmp_path, monkeypatch) -> None:
    original_write = os.write

    def partial_write(fd, data):
        return original_write(fd, data[:1])

    monkeypatch.setattr(os, "write", partial_write)
    staging = RecoveryStaging.create(tmp_path / "staging")
    assert (staging.root / "RECOVERY_NOT_PROMOTABLE").read_bytes() == b"RECOVERY_STAGING_V1\n"
    staging.close()


def test_active_local_api_rejects_recovery_quarantine(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        build_local_api(staging.root / "workspace.sqlite3", private_root=staging.root / "private", token="a" * 32)


def test_active_local_api_rejects_quarantine_in_higher_ancestor(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    nested = staging.root / "nested"
    nested.mkdir()
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        build_local_api(nested / "active.sqlite3", private_root=nested / "private", token="a" * 32)


def test_active_local_api_rejects_hardlink_alias_to_quarantined_database(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    alias = tmp_path / "alias.sqlite3"
    try:
        os.link(staging.root / "workspace.sqlite3", alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    assert os.path.samefile(staging.root / "workspace.sqlite3", alias)
    with pytest.raises(RepositoryIntegrityError, match="link"):
        build_local_api(alias, token="a" * 32)


def test_embedded_quarantine_survives_database_rename(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    renamed = tmp_path / "renamed.sqlite3"
    os.replace(staging.root / "workspace.sqlite3", renamed)
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        build_local_api(renamed, token="a" * 32)


def test_embedded_quarantine_survives_sqlite_snapshot_restore(tmp_path) -> None:
    normal = SQLiteApplicationStore(tmp_path / "normal.sqlite3")
    normal_snapshot = normal.snapshot()
    normal.close()
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.database.restore(normal_snapshot)
    assert staging.database.is_recovery_quarantined() is True
    escaped = tmp_path / "escaped.sqlite3"
    escaped.write_bytes(staging.database.snapshot())
    staging.close()
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        build_local_api(escaped, token="a" * 32)


def test_embedded_private_quarantine_survives_root_rename(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    renamed_private = tmp_path / "renamed-private"
    os.replace(staging.root / "private", renamed_private)
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        build_local_api(tmp_path / "normal.sqlite3", private_root=renamed_private, token="a" * 32)


def test_corrupt_embedded_private_quarantine_fails_closed(tmp_path) -> None:
    staging = RecoveryStaging.create(tmp_path / "staging")
    staging.close()
    renamed_private = tmp_path / "renamed-private"
    os.replace(staging.root / "private", renamed_private)
    marker = renamed_private / ".recovery-not-promotable"
    marker.write_bytes(b"BROKEN\n")
    with pytest.raises(RepositoryIntegrityError, match="corrompido"):
        build_local_api(tmp_path / "normal.sqlite3", private_root=renamed_private, token="a" * 32)


def test_unknown_sqlite_application_identity_fails_closed(tmp_path) -> None:
    store = SQLiteApplicationStore(tmp_path / "unknown.sqlite3")
    store._connection.execute("PRAGMA application_id = 123456")
    store.close()
    with pytest.raises(RepositoryIntegrityError, match="unknown"):
        build_local_api(tmp_path / "unknown.sqlite3", token="a" * 32)


@pytest.mark.parametrize("database", (r"\\server\share\case.sqlite3", r"\\?\C:\case.sqlite3"))
def test_active_local_api_rejects_nonlocal_database_before_filesystem_access(database) -> None:
    with pytest.raises(RepositoryIntegrityError, match="network|device"):
        build_local_api(database, token="a" * 32)


@pytest.mark.parametrize("root", ("relative-staging", r"\\server\share\staging", r"\\?\C:\staging"))
def test_recovery_staging_rejects_nonlocal_or_unanchored_root(root) -> None:
    with pytest.raises(RepositoryIntegrityError, match="root"):
        RecoveryStaging.create(root)


def test_restore_requires_globally_empty_staging_not_only_absent_source_id(tmp_path) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    staging_root = tmp_path / "staging"
    staging = RecoveryStaging.create(staging_root)
    staging.workspaces.create(PericiaWorkspace(WorkspaceId.parse("44444444-4444-4444-8444-444444444444"), "Outro", "2026-08-31T12:00:00+00:00"))
    with pytest.raises(RepositoryConflict, match="empty"):
        RestoreWorkspaceBackup(staging).execute(package)
    assert staging.discarded is True and staging_root.exists()
    source.close()


def test_support_diagnostics_are_sanitized_and_never_egress_private_data(tmp_path) -> None:
    private = PrivateStore()
    source, workspace_id = seeded_store(tmp_path / "source.db", private)
    package = CreateWorkspaceBackup(source.workspaces, source.revisions, private, Clock()).execute(workspace_id)
    diagnostic = collect_support_diagnostics(package)
    rendered = repr(diagnostic)
    assert diagnostic.integrity_status == "PASS" and diagnostic.private_egress is False
    assert "synthetic.pdf" not in rendered and WORKSPACE_ID not in rendered and "private-content" not in rendered
    source.close()

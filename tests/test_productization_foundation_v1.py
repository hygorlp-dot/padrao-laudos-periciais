from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.backend_contract.productization import (
    PRODUCT_RELEASE_VERSION,
    STORAGE_FORMAT_VERSION,
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


def test_backup_contract_rejects_unknown_fields() -> None:
    payload = backup_mapping()
    payload["reinterpret_history"] = True
    with pytest.raises(ValueError, match="fields"):
        workspace_backup_from_mapping(payload)

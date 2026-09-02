"""Direct unit coverage for `validate_pje_intake_payload`.

The E2E test in test_pje_workspace_bridge_v1.py only exercises the happy path
through the parser output; this file pins the structural fail-closed behavior
the application service relies on before ever trusting a PJe inventory.
"""
from __future__ import annotations

import copy

import pytest

from scripts.backend_contract.application.services import validate_pje_intake_payload

WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
CONTENT_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_SHA = "a" * 64


def base_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "workspace_id": WORKSPACE_ID,
        "storage_content_id": CONTENT_ID,
        "source_sha256": SOURCE_SHA,
        "instance_label": "Vara sintética",
        "documents": [
            {"document_id": "DOC-PJE-001", "id_pje": "900001", "title": "Petição sintética",
             "raw_type": "PETICAO", "normalized_type": "PETICAO_INICIAL",
             "page_start": 2, "page_end": 3, "available": True},
        ],
        "party_rows": [],
    }


def test_valid_payload_round_trips_unchanged():
    payload = base_payload()
    assert validate_pje_intake_payload(copy.deepcopy(payload)) == payload


def test_rejects_page_span_where_end_precedes_start():
    payload = base_payload()
    payload["documents"][0]["page_start"], payload["documents"][0]["page_end"] = 5, 4
    with pytest.raises(ValueError, match="page span"):
        validate_pje_intake_payload(payload)


def test_rejects_non_positive_page_numbers():
    payload = base_payload()
    payload["documents"][0]["page_start"] = 0
    with pytest.raises(ValueError, match="page span"):
        validate_pje_intake_payload(payload)


def test_rejects_duplicated_logical_document_ids():
    payload = base_payload()
    payload["documents"].append(dict(payload["documents"][0]))
    with pytest.raises(ValueError, match="duplicated"):
        validate_pje_intake_payload(payload)


def test_rejects_malformed_source_sha256():
    payload = base_payload()
    payload["source_sha256"] = "not-a-sha256"
    with pytest.raises(ValueError, match="source hash"):
        validate_pje_intake_payload(payload)


def test_rejects_foreign_workspace_id_shape():
    payload = base_payload()
    payload["workspace_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_pje_intake_payload(payload)


def test_rejects_foreign_content_id_shape():
    payload = base_payload()
    payload["storage_content_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        validate_pje_intake_payload(payload)


def test_rejects_empty_document_collection():
    payload = base_payload()
    payload["documents"] = []
    with pytest.raises(ValueError, match="collections"):
        validate_pje_intake_payload(payload)


def test_rejects_unknown_top_level_field():
    payload = base_payload()
    payload["extra_field"] = "unexpected"
    with pytest.raises(ValueError, match="payload is invalid"):
        validate_pje_intake_payload(payload)


def test_pje_inventory_survives_backup_and_restore_unchanged():
    """The new artifact kind must round-trip through the portability boundary."""
    import tempfile
    from pathlib import Path

    from scripts.backend_contract.application.models import PericiaWorkspace, WorkspaceId
    from scripts.backend_contract.infrastructure.productization import (
        CreateWorkspaceBackup,
        RecoveryStaging,
        RestoreWorkspaceBackup,
    )
    from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore

    class Clock:
        def now(self):
            from datetime import UTC, datetime

            return datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    tmp_path = Path(tempfile.mkdtemp(prefix="pje-backup-"))
    source = SQLiteApplicationStore(tmp_path / "source.sqlite3")
    workspace_id = WorkspaceId.parse(WORKSPACE_ID)
    source.workspaces.create(
        PericiaWorkspace(workspace_id, "Pericia sintetica", "2026-08-31T12:00:00+00:00")
    )
    payload = base_payload()
    source.revisions.append(
        workspace_id=workspace_id,
        artifact_kind="PJE_INTAKE_V1",
        artifact_id="PJE-INTAKE",
        revision_id="33333333-3333-4333-8333-333333333333",
        created_at="2026-08-31T12:00:00+00:00",
        payload=payload,
    )

    package = CreateWorkspaceBackup(
        source.workspaces, source.revisions, None, Clock(), lambda _: None
    ).execute(workspace_id)
    staging = RecoveryStaging.create(tmp_path / "restored")
    RestoreWorkspaceBackup(staging).execute(package)

    restored = staging.revisions.latest(workspace_id, "PJE_INTAKE_V1", "PJE-INTAKE")
    assert restored is not None, "PJe inventory did not survive restore"
    from scripts.backend_contract.application.models import thaw_payload

    assert validate_pje_intake_payload(thaw_payload(restored.payload)) == payload


def test_rejects_party_row_pole_outside_enum():
    payload = base_payload()
    payload["party_rows"] = [{
        "name": "PARTE", "role": "AUTORA", "pole": "SIDEWAYS",
        "representative_name": "PROCURADOR", "representative_role": "ADVOGADO",
        "page": 1, "occurrence": "linha",
    }]
    with pytest.raises(ValueError, match="party row"):
        validate_pje_intake_payload(payload)

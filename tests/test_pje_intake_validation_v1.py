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
        "schema_version": "1.1.0",
        "status": "OK",
        "diagnostics": [],
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


def test_an_inventory_written_by_an_earlier_build_still_loads():
    """Um payload 1.0.0 persistido nao pode tornar o workspace irrecuperavel."""
    legacy = base_payload()
    legacy["schema_version"] = "1.0.0"
    del legacy["status"], legacy["diagnostics"]
    legacy["party_rows"] = [{
        "name": "PARTE", "role": "AUTORA", "pole": "ACTIVE",
        "representative_name": "ADV", "representative_role": "ADVOGADO",
        "page": 1, "occurrence": "linha",
    }]
    migrated = validate_pje_intake_payload(legacy)
    assert migrated["schema_version"] == "1.1.0"
    assert migrated["status"] == "OK" and migrated["diagnostics"] == []
    assert migrated["party_rows"][0]["document_id"] is None


def test_a_blocked_inventory_must_record_why():
    payload = base_payload()
    payload["status"] = "BLOCKED"
    payload["documents"] = []
    payload["party_rows"] = []
    with pytest.raises(ValueError, match="must say why"):
        validate_pje_intake_payload(dict(payload))
    payload["diagnostics"] = [{"code": "PEN-PJE-001", "detail": "item sem destino"}]
    assert validate_pje_intake_payload(payload)["status"] == "BLOCKED"


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


def test_backup_without_the_pje_source_fails_closed():
    """S-10: um inventario nao pode ser certificado sem a fonte que ele nomeia.

    O round-trip POSITIVO e provado em test_pje_multisource_identity_v1, com
    armazenamento privado real. Aqui prova-se o negativo, que e o que o fecho de
    autoridade existe para impedir: um pacote sem a fonte privada do inventario
    seria restaurado como intacto e deixaria a Case Analysis permanentemente
    indisponivel no workspace restaurado.
    """
    import tempfile
    from pathlib import Path

    from scripts.backend_contract.application.models import PericiaWorkspace, WorkspaceId
    from scripts.backend_contract.infrastructure.productization import (
        CreateWorkspaceBackup,
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
        artifact_id=CONTENT_ID,
        revision_id="33333333-3333-4333-8333-333333333333",
        created_at="2026-08-31T12:00:00+00:00",
        payload=payload,
    )

    from scripts.backend_contract.application.ports import RepositoryIntegrityError

    with pytest.raises(RepositoryIntegrityError, match="PJe source authority is incomplete"):
        CreateWorkspaceBackup(
            source.workspaces, source.revisions, None, Clock(), lambda _: None
        ).execute(workspace_id)


def test_rejects_party_row_pole_outside_enum():
    payload = base_payload()
    payload["party_rows"] = [{
        "name": "PARTE", "role": "AUTORA", "pole": "SIDEWAYS",
        "representative_name": "PROCURADOR", "representative_role": "ADVOGADO",
        "page": 1, "occurrence": "linha",
    }]
    with pytest.raises(ValueError, match="party row"):
        validate_pje_intake_payload(payload)

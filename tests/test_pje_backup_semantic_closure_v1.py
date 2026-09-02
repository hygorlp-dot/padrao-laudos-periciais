"""S-10 terminal: equivalencia SEMANTICA atraves da fronteira de portabilidade.

Nao basta o pacote conter `PJE_INTAKE_V1`. O que precisa sobreviver e o
significado: identidades de fonte, identidades logicas, decisoes profissionais de
disponibilidade, o estado BLOCKED, os diagnosticos que o justificam e a cobertura
nao-completa que dele decorre. Timestamps novos sao legitimos; autoridade e
identidade nao podem mudar.
"""
from __future__ import annotations

import json

import pytest

from scripts.backend_contract.application.models import WorkspaceId, thaw_payload
from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.application.services import validate_pje_intake_payload
from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore
from scripts.backend_contract.infrastructure.productization import (
    CreateWorkspaceBackup,
    RecoveryStaging,
    RestoreWorkspaceBackup,
    VerifyWorkspaceBackup,
    workspace_backup_from_mapping,
    workspace_backup_to_mapping,
)
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_local_api_v1 import TOKEN, http_request
from tests.test_pje_coverage_closure_v1 import _blocked_pje_pdf
from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf


class _Clock:
    def now(self):
        from datetime import UTC, datetime

        return datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


def _semantic_state(runtime, workspace_id):
    """Tudo o que precisa atravessar o backup com o mesmo significado."""
    status, envelope = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
    assert status == 200, envelope
    inventories = {
        item["inventory"]["storage_content_id"]: {
            "status": item["inventory"]["status"],
            "diagnostics": [d["code"] for d in item["inventory"]["diagnostics"]],
            "documents": {
                row["document_id"]: row["available"] for row in item["inventory"]["documents"]
            },
            "source_sha256": item["inventory"]["source_sha256"],
            "instance_label": item["inventory"]["instance_label"],
        }
        for item in envelope["intakes"]
    }
    status, analysis = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    if status == 404:
        status, analysis = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={}
        )
    assert status in {200, 201}, analysis
    snapshot = analysis["snapshot"]
    return {
        "inventories": inventories,
        "coverage": snapshot["coverage"],
        "stale_document_ids": sorted(snapshot["stale_document_ids"]),
        "documents": {
            document["document_id"]: (
                document["storage_content_id"],
                document["source_sha256"],
                document["content_available"],
            )
            for document in snapshot["documents"]
        },
    }


def _build_rich_workspace(tmp_path):
    """Multi-fonte + override profissional + intake BLOCKED + diagnosticos."""
    private = tmp_path / "private"
    provision_private_root(private)
    database = tmp_path / "product.sqlite3"
    good = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    blocked = _blocked_pje_pdf(tmp_path / "b.pdf")

    runtime = build_pericial_local_api(database, private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso rico"})
        workspace_id = workspace["workspace_id"]
        status, a = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=good.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "a.pdf"},
        )
        assert status == 201, a
        status, b = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=blocked.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "b.pdf"},
        )
        assert status == 201, b

        _s, envelope = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        target = next(
            i for i in envelope["intakes"] if i["inventory"]["storage_content_id"] == a["content_id"]
        )
        status, _ = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
                "storage_content_id": a["content_id"],
                "document_id": target["inventory"]["documents"][1]["document_id"],
                "available": False, "expected_revision": target["revision"],
            },
        )
        assert status == 200
        before = _semantic_state(runtime, workspace_id)
    finally:
        runtime.close()
    return database, private, workspace_id, before, a, b


def _package(database, private, workspace_id):
    store = SQLiteApplicationStore(database)
    contents = LocalPrivateContentStore(private)
    try:
        return CreateWorkspaceBackup(
            store.workspaces, store.revisions, contents, _Clock(), lambda _: None
        ).execute(WorkspaceId.parse(workspace_id))
    finally:
        contents.close()
        store.close()


def test_S10_semantic_authority_closure_survives_backup_restore(tmp_path):
    database, private, workspace_id, before, source_a, _source_b = _build_rich_workspace(tmp_path)

    # A cena precisa realmente exercitar o que se quer provar.
    assert len(before["inventories"]) == 2, before
    assert any(item["status"] == "BLOCKED" for item in before["inventories"].values())
    assert any(item["diagnostics"] for item in before["inventories"].values())
    assert before["coverage"]["status"] != "COMPLETE"
    assert any(not available for item in before["inventories"].values()
               for available in item["documents"].values())

    package = _package(database, private, workspace_id)
    VerifyWorkspaceBackup().execute(package)

    staging = RecoveryStaging.create(tmp_path / "restored")
    RestoreWorkspaceBackup(staging).execute(package)
    try:
        restored = {}
        for content_id in before["inventories"]:
            record = staging.revisions.latest(
                WorkspaceId.parse(workspace_id), "PJE_INTAKE_V1", content_id
            )
            assert record is not None, f"inventario de {content_id} nao sobreviveu"
            inventory = validate_pje_intake_payload(thaw_payload(record.payload))
            restored[content_id] = {
                "status": inventory["status"],
                "diagnostics": [d["code"] for d in inventory["diagnostics"]],
                "documents": {row["document_id"]: row["available"] for row in inventory["documents"]},
                "source_sha256": inventory["source_sha256"],
                "instance_label": inventory["instance_label"],
            }
        assert restored == before["inventories"], (
            "o significado do inventario mudou ao atravessar a portabilidade"
        )
        # A decisao profissional especificamente.
        assert any(
            available is False for available in restored[source_a["content_id"]]["documents"].values()
        ), "a exclusao profissional nao sobreviveu ao backup"
    finally:
        staging.close()


@pytest.mark.parametrize("damage", ["missing_source", "missing_intake", "foreign_source_binding"])
def test_S10_negative_backup_cases_fail_closed(tmp_path, damage):
    database, private, workspace_id, _before, source_a, _source_b = _build_rich_workspace(tmp_path)
    package = _package(database, private, workspace_id)
    raw = json.loads(package.decode("utf-8"))

    if damage == "missing_source":
        raw["private_contents"] = [
            item for item in raw["private_contents"] if item["content_id"] != source_a["content_id"]
        ]
    elif damage == "missing_intake":
        raw["artifact_revisions"] = [
            item for item in raw["artifact_revisions"]
            if not (item["artifact_kind"] == "PJE_INTAKE_V1" and item["artifact_id"] == source_a["content_id"])
        ]
    else:
        for item in raw["artifact_revisions"]:
            if item["artifact_kind"] == "PJE_INTAKE_V1" and item["artifact_id"] == source_a["content_id"]:
                item["payload"] = {**item["payload"], "storage_content_id": str(_source_b["content_id"])}

    # Reselar para que a violacao nao seja detectada apenas pelo hash do pacote.
    backup = workspace_backup_from_mapping(raw)
    resealed = workspace_backup_to_mapping(backup)
    tampered = json.dumps(resealed, ensure_ascii=False).encode("utf-8")

    if damage == "missing_intake":
        # Remover o inventario nao corrompe o pacote: ele passa a nao afirmar
        # nada sobre aquela fonte, o que e legitimo. O que nao pode acontecer e
        # o inventario voltar reconstruido por default silencioso.
        staging = RecoveryStaging.create(tmp_path / "restored")
        try:
            try:
                RestoreWorkspaceBackup(staging).execute(tampered)
            except RepositoryIntegrityError:
                return
            record = staging.revisions.latest(
                WorkspaceId.parse(workspace_id), "PJE_INTAKE_V1", source_a["content_id"]
            )
            assert record is None, "um inventario ausente foi reconstruido por default"
        finally:
            staging.close()
        return

    with pytest.raises(RepositoryIntegrityError):
        VerifyWorkspaceBackup().execute(tampered)

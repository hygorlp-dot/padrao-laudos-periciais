"""F8 (#253): anexo PDF de apoio a entrega nao e fonte do caso.

`USER_IMPORT` e origem de armazenamento (o perito enviou o arquivo), nao papel
semantico. Antes desta correcao, todo PDF `USER_IMPORT` era listado como peca dos
autos: anexar um PDF de apoio a entrega deixava a Analise do Caso com fonte nova
nao incorporada, e adicionar item respondia 409 -- a analise congelava.
"""
from __future__ import annotations

import json
import os

import pytest

from scripts.backend_contract.application.content_roles import (
    PRIVATE_CONTENT_ROLE_KIND,
    PrivateContentRoles,
    private_content_role_payload,
    PrivateContentRole,
)
from scripts.backend_contract.application.models import WorkspaceId
from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.application.services import ListCaseDocuments, ListPrivateContents
from tests.test_document_intake_v1 import (
    WORKSPACE_ID,
    ExistingWorkspace,
    MemoryContents,
    PDF,
    document_services,
)


def _pdf(lines):
    from tests.test_property_record_v1 import _text_pdf

    return _text_pdf(lines)


def _runtime(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN

    runtime = build_local_api(tmp_path / "f8.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    return runtime


def _case_with_supporting_pdf(runtime):
    from tests.test_product_integration_oracle_v1 import _http

    status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "F8 sintético"})
    assert status == 201
    root = f"/v1/workspaces/{workspace['workspace_id']}"
    source = _pdf(["PETIÇÃO INICIAL", "Texto sintético da peça dos autos."])
    assert _http(runtime, "POST", root + "/materials", raw_body=source, headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})[0] == 201
    assert _http(runtime, "POST", root + "/case-analysis", {})[0] == 201
    status, before = _http(runtime, "GET", root + "/case-analysis")
    assert status == 200 and before["snapshot"]["source_inventory_stale"] is False
    supporting = _pdf(["ANEXO DE APOIO À ENTREGA", "Planilha sintética de apoio."])
    status, stored = _http(runtime, "POST", root + "/delivery-supporting-files", raw_body=supporting, headers={"Content-Type": "application/pdf", "X-Document-Filename": "anexo.pdf"})
    assert status == 201
    return workspace["workspace_id"], root, before, stored


def test_delivery_supporting_pdf_does_not_become_a_case_source_or_freeze_case_analysis(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http

    runtime = _runtime(tmp_path)
    try:
        _workspace_id, root, before, stored = _case_with_supporting_pdf(runtime)
        status, after = _http(runtime, "GET", root + "/case-analysis")
        assert status == 200
        snapshot = after["snapshot"]
        assert snapshot["source_inventory_stale"] is False
        assert snapshot["unindexed_source_count"] == 0
        assert snapshot["documents"] == before["snapshot"]["documents"]
        assert snapshot["coverage"] == before["snapshot"]["coverage"]
        status, materials = _http(runtime, "GET", root + "/materials")
        assert status == 200
        listed = json.dumps(materials)
        assert stored["content_id"] not in listed and "autos.pdf" in listed
        status, _ = _http(runtime, "POST", root + "/case-analysis/items", {
            "expected_revision": after["revision"], "item_kind": "PERICIAL_OBJECT",
            "text": "Objeto pericial sintético.", "source_document_id": snapshot["documents"][0]["document_id"],
            "page_or_span": "p. 1", "technical_subjects": ["Superfície"], "values": {},
        })
        assert status == 200, "a Analise do Caso nao pode congelar por causa de um anexo de entrega"
    finally:
        runtime.close()


def test_delivery_supporting_role_travels_in_the_backup_bound_to_its_exact_bytes(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, _reseal, http_request

    runtime = _runtime(tmp_path)
    try:
        _workspace_id, root, _before, stored = _case_with_supporting_pdf(runtime)
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
    finally:
        runtime.close()
    verified = VerifyWorkspaceBackup().execute(backup)
    roles = [item for item in verified.artifact_revisions if item["artifact_kind"] == PRIVATE_CONTENT_ROLE_KIND]
    assert [(item["artifact_id"], item["payload"]["role"]) for item in roles] == [(stored["content_id"], "DELIVERY_SUPPORT")]

    raw = json.loads(backup)
    # Papel apontando para bytes que nao vieram no pacote.
    missing = json.loads(backup)
    missing["private_contents"] = [item for item in missing["private_contents"] if item["content_id"] != stored["content_id"]]
    # Papel transplantado para outros bytes do mesmo workspace (a peca dos autos).
    source = next(item for item in raw["private_contents"] if item["content_id"] != stored["content_id"])
    transplanted = json.loads(backup)
    for item in transplanted["artifact_revisions"]:
        if item["artifact_kind"] == PRIVATE_CONTENT_ROLE_KIND:
            item["payload"]["checksum_sha256"] = source["checksum_sha256"]
    for damaged in (missing, transplanted):
        with pytest.raises(RepositoryIntegrityError):
            VerifyWorkspaceBackup().execute(_reseal(damaged))


@pytest.mark.skipif(os.name != "nt", reason="mutable Recovery V1 is supported only on Windows")
def test_delivery_supporting_role_survives_restore(tmp_path):
    from scripts.backend_contract.infrastructure.productization import RecoveryStaging, RestoreWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, http_request

    runtime = _runtime(tmp_path)
    try:
        workspace_id, root, _before, stored = _case_with_supporting_pdf(runtime)
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
    finally:
        runtime.close()
    staging = RecoveryStaging.create(tmp_path / "restored")
    RestoreWorkspaceBackup(staging).execute(backup)
    try:
        record = staging.revisions.latest(WorkspaceId.parse(workspace_id), PRIVATE_CONTENT_ROLE_KIND, stored["content_id"])
        assert record is not None and record.payload["role"] == "DELIVERY_SUPPORT"
    finally:
        staging.close()


class _Revisions:
    def __init__(self, records=None):
        self.records = records or {}

    def latest(self, workspace_id, kind, artifact_id):
        return self.records.get((str(workspace_id), kind, artifact_id))


def _listing(revisions):
    importer, _listed, _reader = document_services()
    contents = importer.contents.contents
    return importer, ListCaseDocuments(ListPrivateContents(ExistingWorkspace(), contents), PrivateContentRoles(revisions))


def test_legacy_user_import_pdf_without_role_remains_a_case_source():
    # Backups e workspaces anteriores nao tem registro de papel. Nada e inferido:
    # o PDF importado pelo usuario continua sendo lido como antes.
    importer, listed = _listing(_Revisions())
    stored = importer.execute(workspace_id=WORKSPACE_ID, original_filename="Autos.pdf", content=PDF, media_type="application/pdf")
    assert listed.execute(WORKSPACE_ID) == (stored,)


def test_role_bound_to_other_bytes_fails_closed_instead_of_choosing_a_side():
    from types import MappingProxyType, SimpleNamespace

    importer, _ = _listing(_Revisions())
    stored = importer.execute(workspace_id=WORKSPACE_ID, original_filename="Autos.pdf", content=PDF, media_type="application/pdf")
    payload = private_content_role_payload(stored, PrivateContentRole.DELIVERY_SUPPORT)
    revisions = _Revisions({(str(WORKSPACE_ID), PRIVATE_CONTENT_ROLE_KIND, str(stored.content_id)): SimpleNamespace(payload=MappingProxyType({**payload, "checksum_sha256": "0" * 64}))})
    listed = ListCaseDocuments(ListPrivateContents(ExistingWorkspace(), importer.contents.contents), PrivateContentRoles(revisions))
    with pytest.raises(RepositoryIntegrityError, match="role diverges"):
        listed.execute(WORKSPACE_ID)


def test_case_document_listing_cannot_be_built_without_the_role_registry():
    for roles in (None, _Revisions()):
        with pytest.raises(TypeError, match="papéis"):
            ListCaseDocuments(ListPrivateContents(ExistingWorkspace(), MemoryContents()), roles)

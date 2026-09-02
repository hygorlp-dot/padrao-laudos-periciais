from __future__ import annotations

import json

from scripts.backend_contract.local_api.composition import build_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_local_api_v1 import TOKEN, http_request


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


def test_non_pje_material_import_still_succeeds_without_pje_inventory(tmp_path):
    """A PDF the strict PJe reader cannot open must not break ordinary material import."""
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "product.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso comum"})
        assert status == 201
        workspace_id = workspace["workspace_id"]
        status, material = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=b"%PDF-1.7\nnao-e-um-pje\n%%EOF\n",
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "documento-comum.pdf"},
        )
        assert status == 201, material
        status, intake = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 404
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        assert status == 201
        assert analysis["snapshot"]["documents"][0]["normalized_type"] == "UNCLASSIFIED"
    finally:
        runtime.close()


def test_valid_pje_pdf_reaches_workspace_logical_documents_and_case_analysis(tmp_path):
    pdf = tmp_path / "autos-sinteticos.pdf"
    pdf_sintetico(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "product.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe sintÃ©tico"})
        assert status == 201
        workspace_id = workspace["workspace_id"]
        status, material = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-sinteticos.pdf"},
        )
        assert status == 201
        status, intake = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200
        hidden = intake["inventory"]["documents"][1]
        status, intake = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
            "document_id": hidden["document_id"], "available": False, "expected_revision": intake["revision"],
        })
        assert status == 200 and intake["inventory"]["documents"][1]["available"] is False
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        assert status == 201
        documents = analysis["snapshot"]["documents"]
        assert [item["document_id"] for item in documents] == ["DOC-PJE-001", "DOC-PJE-002"]
        assert all(item["storage_content_id"] == material["content_id"] for item in documents)
        assert all(item["source_sha256"] == material["checksum_sha256"] for item in documents)
        assert [item["page_count_or_span"] for item in documents] == ["p. 2-3 | PJe 900001", "p. 4 | PJe 900002"]
        assert analysis["snapshot"]["coverage"]["documents_total"] == 2
        assert analysis["snapshot"]["coverage"]["documents_unavailable"] == 1
    finally:
        runtime.close()


def test_second_material_alongside_pje_inventory_fails_closed_not_silently(tmp_path):
    """A second stored material once a PJe inventory exists must not create ambiguous authority."""
    pdf = tmp_path / "autos-sinteticos.pdf"
    pdf_sintetico(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "product.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe"})
        workspace_id = workspace["workspace_id"]
        status, _material = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-sinteticos.pdf"},
        )
        assert status == 201
        status, _second = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=b"%PDF-1.7\noutro-documento\n%%EOF\n",
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "outro.pdf"},
        )
        assert status == 201
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        assert status == 500 and analysis["error"]["code"] == "REPOSITORY_INTEGRITY_FAILURE"
    finally:
        runtime.close()


def test_availability_toggle_rejects_unknown_document_id(tmp_path):
    pdf = tmp_path / "autos-sinteticos.pdf"
    pdf_sintetico(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "product.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe"})
        workspace_id = workspace["workspace_id"]
        _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-sinteticos.pdf"},
        )
        status, intake = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        status, result = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
            "document_id": "DOC-PJE-DOES-NOT-EXIST", "available": False, "expected_revision": intake["revision"],
        })
        assert status == 400 and result["error"]["code"] == "INVALID_REQUEST"
    finally:
        runtime.close()


def test_availability_toggle_rejects_stale_expected_revision(tmp_path):
    pdf = tmp_path / "autos-sinteticos.pdf"
    pdf_sintetico(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "product.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe"})
        workspace_id = workspace["workspace_id"]
        _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-sinteticos.pdf"},
        )
        status, intake = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        stale_revision = intake["revision"]
        document_id = intake["inventory"]["documents"][0]["document_id"]
        _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
            "document_id": document_id, "available": False, "expected_revision": stale_revision,
        })
        status, result = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
            "document_id": document_id, "available": True, "expected_revision": stale_revision,
        })
        assert status == 409 and result["error"]["code"] == "REPOSITORY_CONFLICT"
    finally:
        runtime.close()


def test_workspace_reopen_preserves_pje_inventory(tmp_path):
    """Closing and reopening the runtime against the same store must not lose the logical inventory."""
    pdf = tmp_path / "autos-sinteticos.pdf"
    pdf_sintetico(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    db = tmp_path / "product.sqlite3"
    runtime = build_local_api(db, private_root=private, token=TOKEN)
    runtime.start()
    try:
        status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe"})
        workspace_id = workspace["workspace_id"]
        _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-sinteticos.pdf"},
        )
        status, before = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
    finally:
        runtime.close()
    reopened = build_local_api(db, private_root=private, token=TOKEN)
    reopened.start()
    try:
        status, after = _request(reopened, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200
        assert after["inventory"]["documents"] == before["inventory"]["documents"]
    finally:
        reopened.close()

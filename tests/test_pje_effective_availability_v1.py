"""S-07: a decisao profissional de disponibilidade tem de ser efetiva.

`content_available` e congelado no bootstrap e a extracao de fontes e imutavel
por contrato, entao uma exclusao decidida DEPOIS do bootstrap nao tinha como
alcancar a analise. A projecao acontece na leitura canonica, do mesmo modo que
ja se fazia com hash de fonte -- o historico persistido continua respondendo
"o que era efetivo naquela revisao".
"""
from __future__ import annotations

import json

from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf
from tests.test_local_api_v1 import TOKEN, http_request


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


def _runtime(tmp_path, name="product.sqlite3"):
    private = tmp_path / "private"
    if not private.exists():
        provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / name, private_root=private, token=TOKEN)
    runtime.start()
    return runtime


def _setup(runtime, pdf, filename="autos.pdf"):
    _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
    workspace_id = workspace["workspace_id"]
    status, material = _request(
        runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
        headers={"Content-Type": "application/pdf", "X-Document-Filename": filename},
    )
    assert status == 201, material
    return workspace_id, material


def _intake_for(runtime, workspace_id, content_id):
    status, envelope = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
    assert status == 200, envelope
    return next(i for i in envelope["intakes"] if i["inventory"]["storage_content_id"] == content_id)


def _set_available(runtime, workspace_id, content_id, local_document_id, available):
    intake = _intake_for(runtime, workspace_id, content_id)
    status, result = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability", value={
        "storage_content_id": content_id, "document_id": local_document_id,
        "available": available, "expected_revision": intake["revision"],
    })
    assert status == 200, result
    return result


def _effective(runtime, workspace_id):
    status, analysis = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    if status == 404:
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
    assert status in {200, 201}, analysis
    return analysis["snapshot"]


def _find(snapshot, local_document_id):
    return next(d for d in snapshot["documents"] if d["document_id"].startswith(f"{local_document_id}-"))


def test_S07_exclusion_can_be_reversed_and_the_history_stays_auditable(tmp_path):
    """Reabilitar devolve o documento ao contexto efetivo, sem residuo da exclusao."""
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        content_id = material["content_id"]
        _effective(runtime, workspace_id)  # bootstrap

        _set_available(runtime, workspace_id, content_id, "DOC-PJE-002", False)
        excluded = _effective(runtime, workspace_id)
        target = _find(excluded, "DOC-PJE-002")
        assert target["content_available"] is False
        assert target["document_id"] in excluded["stale_document_ids"]
        assert excluded["coverage"]["documents_unavailable"] == 1
        assert excluded["coverage"]["status"] != "COMPLETE"

        _set_available(runtime, workspace_id, content_id, "DOC-PJE-002", True)
        restored = _effective(runtime, workspace_id)
        back = _find(restored, "DOC-PJE-002")
        assert back["content_available"] is True, "reabilitar nao devolveu o documento"
        assert back["document_id"] not in restored["stale_document_ids"], (
            "o documento seguiu marcado como stale apenas por residuo da exclusao anterior"
        )
        assert restored["coverage"]["documents_unavailable"] == 0

        # O historico das decisoes continua auditavel: cada mudanca gerou revisao.
        intake = _intake_for(runtime, workspace_id, content_id)
        assert intake["revision"] >= 3, "as decisoes nao ficaram registradas como revisoes"
    finally:
        runtime.close()


def test_S07_excluding_one_source_never_touches_another(tmp_path):
    """Duas fontes com o mesmo id local: a exclusao atinge exatamente uma."""
    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, a = _setup(runtime, a_pdf, "a.pdf")
        status, b = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=b_pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "b.pdf"},
        )
        assert status == 201, b
        _effective(runtime, workspace_id)

        _set_available(runtime, workspace_id, a["content_id"], "DOC-PJE-001", False)
        snapshot = _effective(runtime, workspace_id)

        by_source = {}
        for document in snapshot["documents"]:
            by_source.setdefault(document["storage_content_id"], {})[document["document_id"]] = document
        a_docs = by_source[a["content_id"]]
        b_docs = by_source[b["content_id"]]
        a_target = next(d for k, d in a_docs.items() if k.startswith("DOC-PJE-001-"))
        b_target = next(d for k, d in b_docs.items() if k.startswith("DOC-PJE-001-"))

        assert a_target["content_available"] is False
        assert b_target["content_available"] is True, "a exclusao vazou para a outra fonte"
        assert b_target["document_id"] not in snapshot["stale_document_ids"], (
            "a outra fonte foi marcada stale sem que nada dela mudasse"
        )
        assert snapshot["coverage"]["documents_unavailable"] == 1
    finally:
        runtime.close()


def test_S07_every_downstream_reader_uses_the_canonical_effective_projection(tmp_path):
    """Oraculo de bypass: nenhum consumidor pode ler o snapshot congelado direto.

    Se um consumidor material for trocado para ler a revisao persistida em vez da
    projecao canonica, ele deixa de ver a exclusao -- e este teste fica vermelho,
    porque passa a existir um leitor que nao e o objeto canonico.
    """
    from scripts.backend_contract.local_api import composition as composition_module

    runtime = _runtime(tmp_path)
    try:
        pass
    finally:
        runtime.close()

    source = (composition_module.__file__)
    text = open(source, encoding="utf-8").read()
    # Todo servico que consome Case Analysis recebe `get_case_analysis`.
    consumers = (
        "GetPericialPlanning(", "GetTechnicalSnapshot(", "GetReportSnapshot(",
        "StartPericialPlanning(",
    )
    for consumer in consumers:
        index = text.index(consumer)
        window = text[index:index + 400]
        assert "get_case_analysis" in window, (
            f"{consumer} nao recebe a projecao canonica: leria o snapshot congelado"
        )


def test_S07_raw_artifact_route_never_serves_case_analysis(tmp_path):
    """A rota generica de revisoes nao pode virar um bypass da projecao."""
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        _effective(runtime, workspace_id)
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        status, _payload = _request(
            runtime, "GET",
            f"/v1/workspaces/{workspace_id}/artifacts/CASE_ANALYSIS_SNAPSHOT_V1/CASE-ANALYSIS/revisions",
        )
        assert status == 404, (
            "a revisao crua de Case Analysis ficou legivel e contornaria a projecao efetiva"
        )
    finally:
        runtime.close()

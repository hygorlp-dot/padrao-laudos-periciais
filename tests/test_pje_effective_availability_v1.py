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
        # AUDITOR_TEST_CHANGED | INVALID_PREMISE
        # A afirmacao anterior era `in excluded["stale_document_ids"]`, e era ela
        # que fixava o defeito: `stale_document_ids` e o canal de DERIVA DE
        # FONTE, e todo comando a jusante o trata como fatal. Exigir que a
        # decisao profissional entrasse ali tornava verde a paralisia da analise.
        assert target["document_id"] not in excluded["stale_document_ids"], (
            "decisao profissional nao e deriva de fonte; conflatar as duas paralisa a analise"
        )
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


def test_SA03_a_professional_exclusion_does_not_freeze_the_analysis(tmp_path):
    """Excluir um documento nao pode parar a analise inteira.

    Era o desfecho anterior: apos uma exclusao, `POST /case-analysis/items` e
    `POST /case-analysis/reviews` respondiam 409 -- inclusive para itens que
    citavam OUTRO documento -- e a unica forma de voltar a trabalhar era o
    perito desfazer a propria decisao. O sistema coagia ao abandono do juizo
    profissional que esta funcionalidade existe para registrar.

    Duas causas somadas: a decisao entrava no canal de deriva de fonte, e o
    caminho de ESCRITA partia do snapshot projetado, que por construcao diverge
    do predecessor persistido (`source extraction is immutable`).
    """
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        analysis = _effective(runtime, workspace_id)
        documents = analysis["documents"]
        assert len(documents) >= 2, "a cena precisa de outro documento para citar"
        kept = next(d for d in documents if d["document_id"].startswith("DOC-PJE-001"))

        def add_item(revision, text, source_document_id):
            return _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/items", value={
                "expected_revision": revision, "item_kind": "PERICIAL_OBJECT", "text": text,
                "source_document_id": source_document_id, "page_or_span": "p. 1",
                "technical_subjects": ["tema sintetico"], "values": {},
            })

        status, current = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        status, created = add_item(current["revision"], "Objeto anterior.", kept["document_id"])
        assert status == 200, created

        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)

        status, after = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        assert after["snapshot"]["stale_document_ids"] == []
        assert after["snapshot"]["coverage"]["status"] != "COMPLETE"

        # 1. O trabalho continua possivel sobre o que permanece disponivel.
        status, appended = add_item(after["revision"], "Objeto posterior.", kept["document_id"])
        assert status == 200, f"a exclusao congelou a captura de itens: {appended}"

        # 2. A revisao humana tambem.
        status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        status, reviewed = _request(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/reviews", value={
                "expected_revision": fresh["revision"],
                "target_item_id": fresh["snapshot"]["pericial_objects"][0]["item_id"],
                "action": "CONFIRM", "corrected_value": None,
                "reviewer": "PROFESSIONAL-001", "reason": "Revisao humana sintetica.",
            })
        assert status == 200, f"a exclusao congelou a revisao humana: {reviewed}"

        # 3. Mas o documento excluido nao volta pela porta dos fundos.
        status, latest = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        excluded_id = next(
            d["document_id"] for d in latest["snapshot"]["documents"] if not d["content_available"]
        )
        status, refused = add_item(latest["revision"], "Objeto sobre excluido.", excluded_id)
        assert status == 400, f"um item novo citou documento que o perito excluiu: {refused}"
    finally:
        runtime.close()


def test_exclusion_in_one_workspace_never_reaches_another_with_the_same_export(tmp_path):
    """Mesmo PDF (mesmos bytes, mesmos DOC-PJE-*) em dois workspaces: a decisao de A
    fica em A. B continua com a peca disponivel, cobertura propria e trabalho liberado.

    Bytes identicos sao a pior colisao possivel: mesmo sha, mesmos ids locais. So o
    workspace separa as duas autoridades.
    """
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-unica")
    runtime = _runtime(tmp_path)
    try:
        workspace_a, material_a = _setup(runtime, pdf)
        workspace_b, material_b = _setup(runtime, pdf)
        assert material_a["content_id"] != material_b["content_id"], "cada workspace e dono da sua fonte"
        _effective(runtime, workspace_a)
        _effective(runtime, workspace_b)

        _set_available(runtime, workspace_a, material_a["content_id"], "DOC-PJE-002", False)

        a, b = _effective(runtime, workspace_a), _effective(runtime, workspace_b)
        assert _find(a, "DOC-PJE-002")["content_available"] is False
        assert _find(b, "DOC-PJE-002")["content_available"] is True, "a exclusao de A vazou para B"
        assert b["coverage"]["documents_unavailable"] == 0 and b["stale_document_ids"] == []
        intake_b = _intake_for(runtime, workspace_b, material_b["content_id"])
        assert all(row["available"] for row in intake_b["inventory"]["documents"])

        # E B continua trabalhavel citando justamente a peca que A excluiu.
        status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_b}/case-analysis")
        status, added = _request(runtime, "POST", f"/v1/workspaces/{workspace_b}/case-analysis/items", value={
            "expected_revision": fresh["revision"], "item_kind": "PERICIAL_OBJECT", "text": "Objeto em B.",
            "source_document_id": _find(b, "DOC-PJE-002")["document_id"], "page_or_span": "p. 1",
            "technical_subjects": ["tema"], "values": {},
        })
        assert status == 200, added
    finally:
        runtime.close()


def test_exclusion_survives_backup_verify_stage_promote_reopen_and_stays_workable(tmp_path):
    """backup -> verify -> stage -> promote -> reopen, com uma exclusao profissional no meio.

    Depois da recuperacao: a decisao continua la (nada reabilitado em silencio), a peca
    excluida segue fora da autoridade, a analise continua trabalhavel (SA-03 tambem vale
    no workspace recuperado) e reabilitar ainda funciona.
    """
    import os

    import pytest

    if os.name != "nt":
        pytest.skip("a jornada completa de recuperacao mutavel e apenas Windows")
    from tests.test_backup_recovery_reachability_v1 import _api, _json
    from tests.test_backup_recovery_reachability_v1 import _runtime as _recovery_runtime

    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-recuperada")
    source = _recovery_runtime(tmp_path, "source")
    try:
        workspace_id, material = _setup(source, pdf)
        content_id = material["content_id"]
        _effective(source, workspace_id)
        _set_available(source, workspace_id, content_id, "DOC-PJE-002", False)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
        assert _status == 200
    finally:
        source.close()

    target = _recovery_runtime(tmp_path, "target")
    try:
        status, verified = _json(target, "POST", "/v1/recovery/verify", body=package, headers={"Content-Type": "application/octet-stream"})
        assert status == 200, verified
        status, staged = _json(target, "POST", "/v1/recovery/staging", body=package, headers={"Content-Type": "application/octet-stream"})
        assert status in {200, 201} and staged["promotable"] is True, staged
        status, promoted = _json(target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote", value={"confirm": True})
        assert status == 200 and promoted["workspace_id"] == workspace_id, promoted

        # Reaberto: a decisao sobreviveu, sem reabilitacao silenciosa.
        rows = {row["document_id"]: row["available"] for row in _intake_for(target, workspace_id, content_id)["inventory"]["documents"]}
        assert rows["DOC-PJE-002"] is False and rows["DOC-PJE-001"] is True, rows
        restored = _effective(target, workspace_id)
        assert _find(restored, "DOC-PJE-002")["content_available"] is False
        assert restored["stale_document_ids"] == [] and restored["coverage"]["status"] != "COMPLETE"

        # Trabalhavel no workspace recuperado, e a peca excluida nao volta pela porta dos fundos.
        def add(source_document_id, text):
            status, fresh = _request(target, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
            return _request(target, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/items", value={
                "expected_revision": fresh["revision"], "item_kind": "PERICIAL_OBJECT", "text": text,
                "source_document_id": source_document_id, "page_or_span": "p. 1",
                "technical_subjects": ["tema"], "values": {},
            })[0]

        assert add(_find(restored, "DOC-PJE-001")["document_id"], "Objeto apos recuperacao.") == 200
        assert add(_find(restored, "DOC-PJE-002")["document_id"], "Objeto sobre excluido.") == 400

        _set_available(target, workspace_id, content_id, "DOC-PJE-002", True)
        assert _find(_effective(target, workspace_id), "DOC-PJE-002")["content_available"] is True
    finally:
        target.close()

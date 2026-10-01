"""S-07: a decisao profissional de disponibilidade tem de ser efetiva.

`content_available` e congelado no bootstrap e a extracao de fontes e imutavel
por contrato, entao uma exclusao decidida DEPOIS do bootstrap nao tinha como
alcancar a analise. A projecao acontece na leitura canonica, do mesmo modo que
ja se fazia com hash de fonte -- o historico persistido continua respondendo
"o que era efetivo naquela revisao".
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf
from tests.test_local_api_v1 import TOKEN, http_request


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
        # Limite canonico do cliente de teste (teto do LocalServerConfig), o mesmo de
        # test_pje_multisource_identity_v1: importar PJe passa de 5 s em runner carregado.
        timeout=30.0,
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



def _add_item(runtime, workspace_id, kind, text, source_document_id):
    status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    return _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/items", value={
        "expected_revision": fresh["revision"], "item_kind": kind, "text": text,
        "source_document_id": source_document_id, "page_or_span": "p. 1",
        "technical_subjects": ["tema"], "values": {},
    })


def _plan_citations(plan):
    return {
        source["source_document_id"]
        for collection in ("issues", "inspection_requirements", "question_links")
        for item in plan["snapshot"][collection]
        for source in item["derivation"]["source_provenance"]
    }


def test_planning_refuses_items_from_an_excluded_document_until_the_professional_resolves_them(tmp_path):
    """Revisao da #251 (P0 do revisor, P1 do auditor): sem o canal de deriva, o
    Planejamento montava o plano sobre quesito derivado da peca excluida.

    Recusar, e nao filtrar em silencio: o quesito sumiria do plano sem aviso. As duas
    saidas do perito precisam funcionar -- rejeitar o item, ou reabilitar a peca -- e
    e isso que prova que a recusa se deve a exclusao e nao a outro motivo qualquer.
    """
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-plano")
    runtime = _runtime(tmp_path)
    try:
        # Saida 1: rejeitar o item derivado.
        workspace_id, material = _setup(runtime, pdf)
        snapshot = _effective(runtime, workspace_id)
        excluded = _find(snapshot, "DOC-PJE-002")["document_id"]
        kept = _find(snapshot, "DOC-PJE-001")["document_id"]
        status, body = _add_item(runtime, workspace_id, "PERICIAL_QUESTION", "Quesito sobre a peca 2?", excluded)
        assert status == 200, body
        doomed = next(q["item_id"] for q in body["snapshot"]["questions"] if q["provenance"][0]["source_document_id"] == excluded)
        assert _add_item(runtime, workspace_id, "PERICIAL_QUESTION", "Quesito sobre a peca 1?", kept)[0] == 200
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)

        status, _refused = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano"})
        assert status == 400, f"plano montado sobre peca excluida: {status}"

        status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        status, _ = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/reviews", value={
            "expected_revision": fresh["revision"], "target_item_id": doomed, "action": "REJECT",
            "corrected_value": None, "reviewer": "PROFESSIONAL-001", "reason": "Fonte excluida da analise.",
        })
        assert status == 200
        status, plan = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano"})
        assert status == 201, plan
        assert excluded not in _plan_citations(plan) and kept in _plan_citations(plan)

        # Saida 2: reabilitar a peca (outro workspace, mesmo export).
        workspace_b, material_b = _setup(runtime, pdf)
        excluded_b = _find(_effective(runtime, workspace_b), "DOC-PJE-002")["document_id"]
        assert _add_item(runtime, workspace_b, "PERICIAL_QUESTION", "Quesito sobre a peca 2?", excluded_b)[0] == 200
        _set_available(runtime, workspace_b, material_b["content_id"], "DOC-PJE-002", False)
        assert _request(runtime, "POST", f"/v1/workspaces/{workspace_b}/pericial-planning", value={"title": "Plano"})[0] == 400
        _set_available(runtime, workspace_b, material_b["content_id"], "DOC-PJE-002", True)
        status, plan_b = _request(runtime, "POST", f"/v1/workspaces/{workspace_b}/pericial-planning", value={"title": "Plano"})
        assert status == 201, plan_b
        assert excluded_b in _plan_citations(plan_b)
    finally:
        runtime.close()


def test_command_responses_show_the_effective_state_not_the_write_base(tmp_path):
    """Revisao da #251 (F2, P1): o POST devolvia a base de escrita -- cobertura COMPLETE e
    a peca excluida de volta como disponivel -- e a interface exibia isso ate recarregar."""
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-resposta")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        snapshot = _effective(runtime, workspace_id)
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        status, response = _add_item(runtime, workspace_id, "PERICIAL_OBJECT", "Objeto.", _find(snapshot, "DOC-PJE-001")["document_id"])
        assert status == 200, response
        status, reread = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        assert _find(response["snapshot"], "DOC-PJE-002")["content_available"] is False
        assert response["snapshot"]["coverage"]["status"] != "COMPLETE"
        assert response["snapshot"]["coverage"] == reread["snapshot"]["coverage"]
        assert response["snapshot"]["documents"] == reread["snapshot"]["documents"]
    finally:
        runtime.close()


def test_items_derived_from_an_excluded_document_lose_report_and_findings_authority():
    """Revisao da #251 (F4 do revisor, SA251-05 do auditor): filtrar so CASE_DOCUMENT
    deixava a exclusao voltar pelos derivados -- decisao, quesito, participante.

    Unidade direta sobre as funcoes de autoridade: nenhuma outra guarda pode responder
    pela recusa. Controle positivo: derivados de peca disponivel seguem citaveis.
    """
    from dataclasses import replace
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    from scripts.backend_contract.application.report_foundation import _claim_sources, _context_sources
    from scripts.backend_contract.application.technical_findings import _validate_upstream_links
    from scripts.backend_contract.case_analysis import case_analysis_from_mapping
    from tests.test_technical_findings_foundation_v1 import bound_snapshot, upstreams

    root = Path(__file__).resolve().parents[1]
    case = case_analysis_from_mapping(json.loads((root / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")))
    excluded = case.project_effective_availability({"DOC-002": False})
    empty = SimpleNamespace(observations=(), measurements=(), findings=(), decisions=(), question_links=())
    binding = SimpleNamespace(case_analysis_revision=3, inspection_session_revision=2, construction_defect_analysis_revision=1, technical_snapshot_revision=4)

    for name, current in (("disponivel", case), ("excluida", excluded)):
        claims = _claim_sources(binding, current, empty, empty, None)
        context = _context_sources(current, empty)
        live = name == "disponivel"
        assert ("DECISION-001" in claims["COURT_DECISION"][0]) is live, name
        assert ("PART-DEFENDANT" in context["PARTIES"]) is live, name
        assert ("DECISION-001" in context["COURT"]) is live, name
        # O proprio documento, no contexto (ADDRESSES so aceita documentos).
        assert ("DOC-002" in context["ADDRESSES"]) is live, name
        # Derivados de DOC-001 continuam citaveis nos dois estados.
        assert "CLAIM-001" in claims["ALLEGATION"][0] and "QUESTION-001" in context["REQUESTS"], name

    _case_record, _case, _inspection_record, inspection = upstreams()
    snapshot = bound_snapshot()
    link = replace(snapshot.source_links[0], source_kind="CASE_DECISION", source_id="DECISION-001",
                   source_revision=snapshot.source_snapshot.case_analysis_revision)
    # Mesmo link_id: continua pertencendo a sua avaliacao; so a fonte citada muda.
    candidate = replace(snapshot, source_links=(link, *snapshot.source_links[1:]))
    _validate_upstream_links(candidate, case, inspection)  # controle: peca disponivel
    with pytest.raises(ValueError, match="absent from bound upstream"):
        _validate_upstream_links(candidate, excluded, inspection)



def _fixture_case_and_findings():
    from pathlib import Path

    from scripts.backend_contract.case_analysis import case_analysis_from_mapping
    from tests.test_technical_findings_foundation_v1 import bound_snapshot, upstreams

    root = Path(__file__).resolve().parents[1]
    case = case_analysis_from_mapping(json.loads((root / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8")))
    _case_record, _case, _inspection_record, inspection = upstreams()
    return case, bound_snapshot(), inspection


def _neutral_links(snapshot):
    """Todos os vinculos viram MEDICAO: nenhum pode responder pela recusa sob teste."""
    from dataclasses import replace

    measurement = replace(
        snapshot.source_links[0], source_kind="MEASUREMENT", source_id="MEASUREMENT-001",
        source_revision=snapshot.source_snapshot.inspection_session_revision,
    )
    return tuple(replace(measurement, link_id=link.link_id, evidence_id=link.evidence_id) for link in snapshot.source_links)


@pytest.mark.parametrize("kind,source_id", [
    ("CASE_CLAIM", "CLAIM-001"),
    ("CASE_QUESTION", "QUESTION-001"),
    ("DOCUMENTED_ALLEGATION", "OCC-CLAIM-001"),
])
def test_findings_refuse_each_kind_derived_from_an_excluded_document(kind, source_id):
    """Oraculo por conjunto de autoridade em Technical Findings (DOC-001 excluido).

    Os demais vinculos sao neutralizados e os quesitos ligados ficam vazios: so o
    vinculo sob teste pode causar a recusa, e o `match` aponta essa guarda.
    """
    from dataclasses import replace

    from scripts.backend_contract.application.technical_findings import _validate_upstream_links

    case, snapshot, inspection = _fixture_case_and_findings()
    excluded = case.project_effective_availability({"DOC-001": False})
    links = _neutral_links(snapshot)
    link = replace(links[0], source_kind=kind, source_id=source_id, source_revision=snapshot.source_snapshot.case_analysis_revision)
    candidate = replace(snapshot, source_links=(link, *links[1:]), question_links=())
    _validate_upstream_links(candidate, case, inspection)  # controle: peca disponivel
    with pytest.raises(ValueError, match="absent from bound upstream"):
        _validate_upstream_links(candidate, excluded, inspection)


def test_findings_refuse_a_question_link_to_a_question_derived_from_an_excluded_document():
    from dataclasses import replace

    from scripts.backend_contract.application.technical_findings import _validate_upstream_links

    case, snapshot, inspection = _fixture_case_and_findings()
    assert any(link.question_id == "QUESTION-001" for link in snapshot.question_links)
    candidate = replace(snapshot, source_links=_neutral_links(snapshot))
    _validate_upstream_links(candidate, case, inspection)  # controle
    with pytest.raises(ValueError, match="question identity"):
        _validate_upstream_links(candidate, case.project_effective_availability({"DOC-001": False}), inspection)


def test_report_authority_and_source_picker_drop_items_derived_from_an_excluded_document():
    """Oraculo por conjunto do laudo: ALLEGATION, CLAIM_AND_GROUNDS, REQUESTS e o seletor.

    O seletor (`ListReportSources`) precisa oferecer exatamente o que o save aceita.
    """
    from types import SimpleNamespace

    from scripts.backend_contract.application.report_foundation import ListReportSources, _claim_sources, _context_sources

    case, snapshot, inspection = _fixture_case_and_findings()
    empty = SimpleNamespace(observations=(), measurements=(), findings=(), decisions=(), question_links=())
    binding = SimpleNamespace(case_analysis_revision=3, inspection_session_revision=2, construction_defect_analysis_revision=1, technical_snapshot_revision=4)

    def offered(current):
        listing = ListReportSources(
            SimpleNamespace(execute=lambda _w: (None, current)),
            SimpleNamespace(execute=lambda _w: (None, inspection)),
            SimpleNamespace(execute=lambda _w: (None, snapshot)),
        ).execute("workspace")
        return json.dumps(listing, ensure_ascii=False, default=str)

    for current, live in ((case, True), (case.project_effective_availability({"DOC-001": False}), False)):
        claims = _claim_sources(binding, current, empty, empty, None)
        context = _context_sources(current, empty)
        assert ("CLAIM-001" in claims["ALLEGATION"][0]) is live
        assert ("CLAIM-001" in context["CLAIM_AND_GROUNDS"]) is live
        assert ("QUESTION-001" in context["REQUESTS"]) is live
        picker = offered(current)
        assert ('"CLAIM-001"' in picker) is live, "seletor e save divergem para a alegacao"
        assert ('"QUESTION-001"' in picker) is live, "seletor e save divergem para o quesito"


def test_review_command_response_shows_the_effective_state(tmp_path):
    """O POST de revisao tambem devolve o read-model, nao a base de escrita."""
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-revisao")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        snapshot = _effective(runtime, workspace_id)
        status, body = _add_item(runtime, workspace_id, "PERICIAL_OBJECT", "Objeto.", _find(snapshot, "DOC-PJE-001")["document_id"])
        assert status == 200, body
        target = body["snapshot"]["pericial_objects"][0]["item_id"]
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        status, reviewed = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/reviews", value={
            "expected_revision": fresh["revision"], "target_item_id": target, "action": "CONFIRM",
            "corrected_value": None, "reviewer": "PROFESSIONAL-001", "reason": "Revisao sintetica.",
        })
        assert status == 200, reviewed
        assert _find(reviewed["snapshot"], "DOC-PJE-002")["content_available"] is False
        assert reviewed["snapshot"]["coverage"]["status"] != "COMPLETE"
    finally:
        runtime.close()


def test_planning_save_guard_refuses_on_its_own():
    """A guarda do Save do Planejamento, isolada da do Start. O plano inicial e gerado pelo
    proprio Start sobre a analise DISPONIVEL (proposta pura, como o produto a monta) e depois
    salvo contra a analise com a peca excluida: so a guarda do Save pode recusar, e recusa
    antes da validacao do vinculo, com a mensagem propria."""
    import uuid
    from contextlib import nullcontext

    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.backend_contract.application.pericial_planning import SavePericialPlanning, StartPericialPlanning

    case, _snapshot, _inspection = _fixture_case_and_findings()
    workspace = WorkspaceId.parse(case.workspace_id)
    ids = SimpleNamespace(new_uuid=uuid.uuid4)
    captured = []
    StartPericialPlanning(
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3), case)),
        SimpleNamespace(execute=lambda _w, snapshot, *_a, **_k: captured.append(snapshot) or SimpleNamespace(revision=1)),
        ids,
    ).execute(workspace, title="Plano sintetico")
    (proposal,) = captured

    excluded = case.project_effective_availability({"DOC-001": False})
    service = SavePericialPlanning(
        SimpleNamespace(append_if_latest=lambda **_k: pytest.fail("nao pode gravar")),
        SimpleNamespace(execute=lambda *_a: pytest.fail("nao pode chegar a revisao")),
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3), excluded)),
        nullcontext, SimpleNamespace(now=lambda: None), ids,
    )
    with pytest.raises(ValueError, match="cannot build on items derived from a document excluded"):
        service.execute(workspace, proposal, None)

def test_a_gap_extracted_from_a_document_later_excluded_blocks_planning_like_any_derived_item(tmp_path):
    """Revisao da #251 (F3): a isencao de lacunas por TIPO reabria o P0 -- uma lacuna
    criada enquanto a peca estava disponivel foi extraida do conteudo dela; excluida a
    peca, a lacuna ainda guiava o plano.

    A regra e uniforme: nenhuma lacuna fica isenta (ver derived_from_unavailable). Lacuna
    derivada de peca excluida bloqueia o plano, e rejeita-la o libera.
    """
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-lacuna")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        snapshot = _effective(runtime, workspace_id)
        excluded = _find(snapshot, "DOC-PJE-002")["document_id"]
        status, body = _add_item(runtime, workspace_id, "EVIDENCE_GAP", "Lacuna extraida da peca 2.", excluded)
        assert status == 200, body
        gap = body["snapshot"]["gaps"][0]["item_id"]
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        assert _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano"})[0] == 400

        status, fresh = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        assert _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/reviews", value={
            "expected_revision": fresh["revision"], "target_item_id": gap, "action": "REJECT",
            "corrected_value": None, "reviewer": "PROFESSIONAL-001", "reason": "Fonte excluida.",
        })[0] == 200
        status, plan = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano"})
        assert status == 201, plan
    finally:
        runtime.close()



def test_a_gap_created_in_a_re_enable_window_blocks_planning_after_re_exclusion(tmp_path):
    """Auditoria da #251, rodada 3 (SA251R3-01): excluir antes do bootstrap, reabilitar,
    criar uma lacuna citando a peca, excluir de novo -- a lacuna escapava da isencao
    por `stale` (a disponibilidade voltava ao valor congelado no bootstrap) e o plano
    saia com 201 apoiado na peca excluida.

    Sem isencao nenhuma, a lacuna e derivada como qualquer item.
    """
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-janela")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        content_id = material["content_id"]
        _set_available(runtime, workspace_id, content_id, "DOC-PJE-002", False)  # antes do bootstrap
        snapshot = _effective(runtime, workspace_id)
        assert _find(snapshot, "DOC-PJE-002")["content_available"] is False
        _set_available(runtime, workspace_id, content_id, "DOC-PJE-002", True)  # janela de reabilitacao
        reopened = _effective(runtime, workspace_id)
        status, body = _add_item(runtime, workspace_id, "EVIDENCE_GAP", "Lacuna da janela.", _find(reopened, "DOC-PJE-002")["document_id"])
        assert status == 200, body
        _set_available(runtime, workspace_id, content_id, "DOC-PJE-002", False)  # nova exclusao
        status, plan = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano"})
        assert status == 400, f"plano montado sobre lacuna da peca excluida: {status} {plan}"
    finally:
        runtime.close()


def test_a_legacy_plan_built_on_an_excluded_source_keeps_accepting_decisions(tmp_path, monkeypatch):
    """Auditoria da #251, rodada 4 (SA251R4-01): um plano vindo da main, montado sobre uma
    lacuna que citava a propria peca ausente, passava a recusar TODA decisao -- inclusive
    sobre itens sem relacao com a peca. Na main a mesma decisao respondia 200.

    A guarda do Save agora julga so o que o snapshot PASSA a referenciar. O plano legado e
    simulado desligando exatamente as duas guardas que a main nao tinha; dai em diante, o
    codigo atual puro. (Refazer um plano que ficou stale e o F7, #252, anterior a esta PR.)
    """
    from scripts.backend_contract.application import case_analysis as app_case
    from scripts.backend_contract.application import pericial_planning as app_plan

    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-legado")
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _setup(runtime, pdf)
        _set_available(runtime, workspace_id, material["content_id"], "DOC-PJE-002", False)
        snapshot = _effective(runtime, workspace_id)
        excluded = _find(snapshot, "DOC-PJE-002")["document_id"]
        assert _add_item(runtime, workspace_id, "PERICIAL_QUESTION", "Quesito sintetico?", _find(snapshot, "DOC-PJE-001")["document_id"])[0] == 200

        real = app_case.GetCaseAnalysis.execute_for_command
        with monkeypatch.context() as legacy:  # era main: sem as duas guardas
            legacy.setattr(app_case.GetCaseAnalysis, "execute_for_command", lambda self, w: (lambda r: (r[0], r[1], {k: True for k in r[2]}))(real(self, w)))
            legacy.setattr(app_plan, "_refuse_new_references_to_unavailable_documents", lambda *a, **k: None)
            assert _add_item(runtime, workspace_id, "EVIDENCE_GAP", "Anexo tecnico indicado nao esta disponivel.", excluded)[0] == 200
            assert _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", value={"title": "Plano legado"})[0] == 201

        # Codigo atual: o plano legado segue decidivel.
        status, plan = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pericial-planning")
        assert status == 200 and plan["snapshot"]["upstream_stale"] is False
        target = next(item for collection in ("inspection_requirements", "issues", "gaps", "risks", "required_documents") for item in plan["snapshot"][collection])
        status, decided = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning/decisions", value={
            "expected_revision": plan["revision"], "target_item_id": target["item_id"], "action": "APPROVE",
            "reviewer": "PROFESSIONAL-001", "reason": "Revisao.", "decided_value": None,
        })
        assert status == 200, f"plano legado travado: {status} {decided}"
    finally:
        runtime.close()


def test_planning_save_update_refuses_only_newly_introduced_references():
    """Numa atualizacao, o Save julga so as referencias NOVAS: o que o predecessor ja
    referenciava passa (plano legado segue decidivel), o que entra agora e recusado.

    O plano e revinculado ao digest da analise COM a peca excluida para que a validacao
    do vinculo passe -- assim so a guarda de referencias pode responder pela recusa.
    """
    import uuid
    from contextlib import nullcontext
    from dataclasses import replace

    from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId
    from scripts.backend_contract.application.pericial_planning import SavePericialPlanning, StartPericialPlanning
    from scripts.backend_contract.pericial_planning import case_analysis_digest, pericial_planning_to_mapping

    case, _snapshot, _inspection = _fixture_case_and_findings()
    workspace = WorkspaceId.parse(case.workspace_id)
    ids = SimpleNamespace(new_uuid=uuid.uuid4)
    captured = []
    StartPericialPlanning(
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3), case)),
        SimpleNamespace(execute=lambda _w, snapshot, *_a, **_k: captured.append(snapshot) or SimpleNamespace(revision=1)),
        ids,
    ).execute(workspace, title="Plano sintetico")
    excluded = case.project_effective_availability({"DOC-001": False})
    plan = replace(captured[0], plan=replace(captured[0].plan, case_analysis_digest=case_analysis_digest(excluded)))
    derived = {item.item_id for item in excluded.material_items if excluded.derived_from_unavailable(item)}
    collection, index = next(
        (name, position) for name in ("issues", "inspection_requirements", "required_documents", "risks", "gaps")
        for position, item in enumerate(getattr(plan, name))
        if set(item.derivation.case_analysis_item_ids) & derived
    )
    # Predecessor identico, exceto que aquele item citava um item NAO derivado (OBJECT-001,
    # da DOC-002): as contagens do plano ficam intactas e so a referencia muda.
    items = list(getattr(plan, collection))
    items[index] = replace(items[index], derivation=replace(items[index].derivation, case_analysis_item_ids=("OBJECT-001",)))
    assert "OBJECT-001" not in derived
    without = replace(plan, **{collection: tuple(items)})

    def service(previous):
        record = ArtifactRevision(workspace, "PERICIAL_PLANNING_V1", "PERICIAL-PLANNING", str(uuid.uuid4()), 1,
                                 "2026-09-30T12:00:00+00:00", "0" * 64, pericial_planning_to_mapping(previous))
        return SavePericialPlanning(
            SimpleNamespace(append_if_latest=lambda **_k: SimpleNamespace(revision=2)),
            SimpleNamespace(execute=lambda *_a: record),
            SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3, artifact_kind="CASE_ANALYSIS_SNAPSHOT_V1",
                                                             artifact_id="CASE-ANALYSIS", checksum_sha256="c" * 64), excluded)),
            nullcontext, SimpleNamespace(now=lambda: __import__("datetime").datetime(2026, 9, 30, 12, tzinfo=__import__("datetime").UTC)), ids,
        )

    service(plan).execute(workspace, plan, 1)  # nada novo: passa, mesmo com derivados ja referenciados
    with pytest.raises(ValueError, match="cannot build on items derived from a document excluded"):
        service(without).execute(workspace, plan, 1)  # o item derivado entra agora: recusado

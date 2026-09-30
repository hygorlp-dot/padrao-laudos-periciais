"""S-08: completude nao pode ser inferida da ausencia de excecao.

    PROCESSING_FINISHED  !=  CONTENT_COMPLETELY_UNDERSTOOD

A formula canonica de `CaseAnalysisCoverage` ja diz que COMPLETE exige que TODO
documento indexado tenha sido analisado. O buraco era o conjunto: quando o export
PJe era reconhecido mas nao podia ser decomposto, a fonte entrava como um
documento opaco marcado como analisado, e o resto conhecido e nao processado
simplesmente nao existia na contagem.
"""
from __future__ import annotations

import json

from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
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


def _blocked_pje_pdf(path):
    """Export PJe com item de indice sem destino segmentavel: pendencia aberta.

    E a imperfeicao mais ordinaria de um export real -- `pendencias` existe no
    manifesto justamente porque isso e esperado.
    """
    from pypdf import PdfReader, PdfWriter

    pdf_sintetico(path)
    reader = PdfReader(str(path))
    writer = PdfWriter()
    # Remover a pagina que carrega o rodape do segundo documento deixa o item de
    # indice sem destino: o manifesto fica BLOQUEADO, mas o PDF segue valido.
    for number, page in enumerate(reader.pages, 1):
        if number != 4:
            writer.add_page(page)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def _workspace(runtime):
    _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
    return workspace["workspace_id"]


def _import(runtime, workspace_id, pdf, filename):
    status, material = _request(
        runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
        headers={"Content-Type": "application/pdf", "X-Document-Filename": filename},
    )
    assert status == 201, material
    return material


def _coverage(runtime, workspace_id):
    status, analysis = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    if status == 404:
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
    assert status in {200, 201}, analysis
    return analysis["snapshot"]["coverage"]


def test_A_a_fully_understood_export_may_close_coverage(tmp_path):
    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    runtime = _runtime(tmp_path)
    try:
        workspace_id = _workspace(runtime)
        _import(runtime, workspace_id, pdf, "a.pdf")
        coverage = _coverage(runtime, workspace_id)
        assert coverage["status"] == "COMPLETE", coverage
        assert coverage["documents_failed"] == 0
    finally:
        runtime.close()


def test_C_a_blocked_intake_can_never_report_complete(tmp_path):
    """Integracao S-01 <-> S-08: import bem-sucedido nao implica analise completa."""
    pdf = _blocked_pje_pdf(tmp_path / "bloqueado.pdf")
    runtime = _runtime(tmp_path)
    try:
        workspace_id = _workspace(runtime)
        material = _import(runtime, workspace_id, pdf, "bloqueado.pdf")

        status, envelope = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200, envelope
        inventory = envelope["intakes"][0]["inventory"]
        assert inventory["status"] == "BLOCKED", inventory
        assert inventory["diagnostics"], "um inventario bloqueado tem de dizer por que"

        coverage = _coverage(runtime, workspace_id)
        assert coverage["status"] != "COMPLETE", (
            f"resto conhecido e nao processado reportado como completo: {coverage}"
        )
        assert coverage["documents_failed"] >= 1, coverage

        # O material continua sendo material legitimo.
        status, listed = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert status == 200
        assert [item["content_id"] for item in listed["items"]] == [material["content_id"]]
    finally:
        runtime.close()


def test_G_one_blocked_source_prevents_workspace_level_completeness(tmp_path):
    """Fonte A entendida, fonte B bloqueada: o workspace nao esta completo."""
    good = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    blocked = _blocked_pje_pdf(tmp_path / "b.pdf")
    runtime = _runtime(tmp_path)
    try:
        workspace_id = _workspace(runtime)
        _import(runtime, workspace_id, good, "a.pdf")
        _import(runtime, workspace_id, blocked, "b.pdf")
        coverage = _coverage(runtime, workspace_id)
        assert coverage["status"] == "PARTIAL", coverage
        assert coverage["documents_failed"] >= 1, coverage
    finally:
        runtime.close()


def test_S08_blocked_state_survives_reopen(tmp_path):
    """Nenhum default de desserializacao pode normalizar o bloqueio para completo."""
    pdf = _blocked_pje_pdf(tmp_path / "bloqueado.pdf")
    database = tmp_path / "product.sqlite3"
    runtime = _runtime(tmp_path)
    try:
        workspace_id = _workspace(runtime)
        _import(runtime, workspace_id, pdf, "bloqueado.pdf")
        before = _coverage(runtime, workspace_id)
        assert before["status"] != "COMPLETE"
    finally:
        runtime.close()

    reopened = build_pericial_local_api(database, private_root=tmp_path / "private", token=TOKEN)
    reopened.start()
    try:
        status, envelope = _request(reopened, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200
        assert envelope["intakes"][0]["inventory"]["status"] == "BLOCKED"
        assert envelope["intakes"][0]["inventory"]["diagnostics"]
        after = _coverage(reopened, workspace_id)
        assert after == before, f"a cobertura mudou ao reabrir: {before} -> {after}"
    finally:
        reopened.close()


def test_S08_party_table_interrupted_is_recorded_not_discarded(tmp_path):
    """O parser dizer que desistiu no meio da tabela e informacao, nao ruido."""
    from scripts.backend_contract.application.pje_party_table import (
        PjePartyTableState,
        parse_pje_party_table,
    )

    page = (
        "PARTES PROCURADOR\n"
        "POLO ATIVO: MARIA DA SILVA (AUTORA) JOAO ADVOGADO (ADVOGADO)\n"
        "POLO PASSIVO: PEDRO SEM ADVOGADO (REQUERIDO)\n"
        "POLO PASSIVO: UNIAO (REQUERIDA) DEFENSORIA PUBLICA (DEFENSOR)\n"
    )
    parsed = parse_pje_party_table(page)
    assert parsed.final_state is PjePartyTableState.TERMINATED
    assert len(parsed.rows) < 3, "a fixture precisa exercitar a desistencia do parser"

    import inspect

    from scripts.backend_contract.application import services

    body = inspect.getsource(services._pje_inventory_payload)
    assert "final_state" in body, "o construtor do inventario voltou a descartar o sinal"
    assert "PJE_TABELA_PARTES_INTERROMPIDA" in body


def _duplicated_index_pje_pdf(path):
    """Export cujo indice lista o MESMO documento duas vezes.

    Caso real: reexportacao concatenada, ou autos em dois volumes baixados
    juntos. `validar_integridade` responde por `erros` -- e `erros` e uma lista
    de STRING, ao contrario de `conflitos` e `pendencias`, que sao registros.
    """
    from pypdf import PdfReader, PdfWriter

    base = path.with_name(f"base-{path.name}")
    pdf_sintetico(base)
    reader = PdfReader(str(base))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for page in list(reader.pages)[1:]:
        writer.add_page(page)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def test_SA02_a_manifest_error_is_recorded_as_BLOCKED_not_raised_as_internal_error(tmp_path):
    """O canal `erros` do manifesto e o que mais marca BLOQUEADO -- e era o unico
    que nunca chegava a ser registrado.

    Os tres canais de diagnostico tem formas diferentes (`erros` sao strings;
    `conflitos` e `pendencias` sao registros). Trata-los como uma forma so
    levantava `AttributeError`, que nao esta em `_NOT_A_READABLE_PJE_EXPORT` e
    portanto escapava da porta como erro interno: 500 na importacao e 404 no
    inventario, exatamente onde o produto deveria dizer "e um PJe, e nao consegui
    separa-lo, e aqui esta o porque".
    """
    pdf = _duplicated_index_pje_pdf(tmp_path / "duplicado.pdf")
    runtime = _runtime(tmp_path)
    try:
        workspace_id = _workspace(runtime)
        # `_import` ja afirma 201: hoje isto e 500, porque a excecao escapa da porta.
        _import(runtime, workspace_id, pdf, "duplicado.pdf")

        status, envelope = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200, envelope
        inventory = envelope["intakes"][0]["inventory"]
        assert inventory["status"] == "BLOCKED"
        assert inventory["diagnostics"], "um BLOCKED sem diagnostico nao diz por que"
        # A identidade do documento divergente precisa sobreviver ao diagnostico:
        # sem ela o perito sabe que falhou, mas nao onde.
        codes = {item["code"] for item in inventory["diagnostics"]}
        assert "DOC-PJE-001" in codes, codes
        assert all(item["detail"] for item in inventory["diagnostics"])

        # E a consequencia: nada disso pode fechar cobertura.
        assert _coverage(runtime, workspace_id)["status"] != "COMPLETE"
    finally:
        runtime.close()



def test_SA251_02_an_import_that_fails_after_storing_bytes_never_yields_complete_coverage(tmp_path):
    """Auditoria da #251 (SA251-02, P1; era o SA-06 de setembro, nunca reparado).

    A importacao grava os bytes ANTES de extrair e derivar o inventario PJe. Uma falha
    inesperada nesse intervalo respondia 500 -- correto -- mas a fonte ficava gravada e
    a Analise do Caso fechava COMPLETE "analisando" algo que nunca foi lido.

    O armazenamento privado nao tem descarte (e cria-lo mexeria na fronteira de
    confianca), entao o reparo e na mentira, nao nos bytes: fonte cuja importacao nao
    chegou ao fim nao conta como analisada. Controle: a mesma composicao com um adapter
    que funciona fecha COMPLETE.
    """
    from scripts.backend_contract.local_api.composition import build_local_api
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    class _Explodes:
        def logical_inventory(self, *_args, **_kwargs):
            raise RuntimeError("falha inesperada sintetica na derivacao PJe")

    pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-falha")
    for name, adapter, expected_import, complete in (
        ("controle", PjeIntakeAdapter(), 201, True),
        ("falha", _Explodes(), 500, False),
    ):
        private = tmp_path / f"private-{name}"
        provision_private_root(private)
        runtime = build_local_api(tmp_path / f"{name}.sqlite3", private_root=private, token=TOKEN, pje_intake=adapter)
        runtime.start()
        try:
            _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": name})
            workspace_id = workspace["workspace_id"]
            status, _material = _request(
                runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
                headers={"Content-Type": "application/pdf", "X-Document-Filename": "a.pdf"},
            )
            assert status == expected_import, (name, status)
            coverage = _coverage(runtime, workspace_id)
            assert (coverage["status"] == "COMPLETE") is complete, (name, coverage)
            if not complete:
                assert coverage["documents_failed"] >= 1, coverage
        finally:
            runtime.close()

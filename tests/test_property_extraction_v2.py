"""#269 — busca de dados do imovel em camadas, sem confundir endereco de parte.

Todo texto e sintetico. Cada caso afirma o que deve virar proposta e, tao
importante quanto, o que nunca pode virar.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.backend_contract.property_record import PropertyEvidence, property_proposals


def _page(text, number=1, mode="NATIVE_TEXT"):
    return SimpleNamespace(number=number, text=text, extraction_mode=SimpleNamespace(value=mode), confidence=None if mode == "NATIVE_TEXT" else 0.91)


def _found(*pages, include_legacy_labels=False):
    proposals = property_proposals("w", "d", "a" * 64, "autos.pdf", list(pages), include_legacy_labels=include_legacy_labels)
    return proposals, {(p.field, p.value) for p in proposals}


def test_label_level_is_byte_identical_to_v1():
    proposals, found = _found(_page("Logradouro do imóvel: Rua Sintética\nÁrea privativa: 42,50 m²\n"))
    assert ("street", "Rua Sintética") in found and ("private_area_m2", "42,50") in found
    label = next(p for p in proposals if p.field == "street")
    assert label.evidence.method == "LABEL_NATIVE_TEXT_V1" and label.evidence.excerpt == "Logradouro do imóvel: Rua Sintética"
    assert label.strength == "STRONG"


def test_petition_narrative_binds_the_subject_property():
    text = (
        "A parte autora adquiriu o imóvel objeto da ação, situado na Rua das Acácias Sintéticas, nº 120, "
        "Bairro Jardim Sintético, CEP 50000-000, no Residencial Flores Sintéticas, apartamento nº 302, Bloco B.\n"
    )
    proposals, found = _found(_page(text))
    for expected in (
        ("street", "Rua das Acácias Sintéticas"), ("number", "120"), ("neighborhood", "Jardim Sintético"),
        ("postal_code", "50000-000"), ("development", "Residencial Flores Sintéticas"), ("unit", "302"), ("block", "B"),
    ):
        assert expected in found, expected
    street = next(p for p in proposals if p.field == "street")
    assert street.strength == "STRONG" and street.evidence.method == "CONTEXT_BOUND_NATIVE_TEXT_V2"
    assert street.value in street.evidence.excerpt and "imóvel objeto" in street.evidence.excerpt


def test_financing_contract_patterns_without_labels():
    text = (
        "CONTRATO DE COMPRA E VENDA DE IMÓVEL RESIDENCIAL, MÚTUO E ALIENAÇÃO FIDUCIÁRIA EM GARANTIA\n"
        "Contrato nº 8.4444.0123456-7\n"
        "O imóvel objeto deste contrato possui área privativa de 41,85 m² e área construída de 47,10 m².\n"
        "Valor de compra e venda: R$ 120.000,00, no âmbito do Programa Minha Casa, Minha Vida.\n"
    )
    proposals, found = _found(_page(text))
    assert ("contract_number", "8.4444.0123456-7") in found
    assert ("private_area_m2", "41,85") in found and ("constructed_area_m2", "47,10") in found
    assert ("contractual_value", "120.000,00") in found
    assert ("program", "Programa Minha Casa, Minha Vida") in found
    assert all(p.evidence.method.endswith("_V2") or p.evidence.method.endswith("_V1") for p in proposals)


def test_technical_report_and_delivery_term():
    proposals, found = _found(
        _page("PARECER TÉCNICO\nA unidade habitacional vistoriada fica no Condomínio Residencial Lagoa Sintética, Quadra 7, casa nº 15.\n"),
        _page("TERMO DE ENTREGA\nO habite-se do empreendimento foi expedido em 10/03/2015, conforme documento da construtora.\n", number=2),
    )
    assert ("development", "Condomínio Residencial Lagoa Sintética") in found
    assert ("quadra", "7") in found and ("unit", "15") in found
    assert ("habite_se_date", "10/03/2015") in found


@pytest.mark.parametrize(
    "text",
    [
        "FULANA SINTÉTICA, brasileira, residente e domiciliada na Rua dos Autores Sintéticos, nº 45, Bairro Centro, CEP 51111-111.\n",
        "ADVOGADA SINTÉTICA, OAB/PE 00000, com escritório na Avenida dos Advogados, nº 900, Bairro Boa Vista.\n",
        "EMPRESA SINTÉTICA S.A., CNPJ 00.000.000/0001-00, com sede na Rua das Empresas, nº 10.\n",
        "Excelentíssimo Juízo da 1ª Vara Federal, Fórum Sintético, Avenida da Justiça, nº 1.\n",
        "Conforme julgado na Apelação nº 0000000-00.2020.4.05.0000 (Rel. Des. Sintético), o imóvel situado na Rua do Precedente, nº 3, apresentava vícios.\n",
    ],
)
def test_party_lawyer_court_and_precedent_addresses_never_become_property(text):
    _, found = _found(_page(text))
    assert not {field for field, _ in found} & {"street", "number", "neighborhood", "postal_code", "unit", "block"}, found


def test_party_qualification_does_not_leak_through_labels_either():
    qualification = "Requerente: FULANA SINTÉTICA\nResidente e domiciliada no endereço abaixo\nCEP: 52222-222\nBairro: Centro Sintético\n"
    _, found = _found(_page(qualification))
    assert ("postal_code", "52222-222") not in found and ("neighborhood", "Centro Sintético") not in found
    # A verificacao do backup continua aceitando a evidencia de rotulo ja confirmada antes.
    _, legacy = _found(_page(qualification), include_legacy_labels=True)
    assert ("postal_code", "52222-222") in legacy


def test_conflicting_values_stay_side_by_side():
    proposals, _ = _found(
        _page("O imóvel objeto da ação possui área privativa de 41,85 m².\n"),
        _page("Matrícula nº 12.345 — área privativa de 42,10 m² da unidade habitacional.\n", number=3),
    )
    areas = sorted(p.value for p in proposals if p.field == "private_area_m2")
    assert areas == ["41,85", "42,10"]


def test_ambiguous_context_is_only_a_possible_proposal():
    text = "CONTRATO DE COMPRA E VENDA\nCLÁUSULA SEGUNDA\nEndereço: Rua da Cláusula Sintética, nº 77.\n"
    proposals, found = _found(_page(text))
    street = [p for p in proposals if p.field == "street" and p.value == "Rua da Cláusula Sintética"]
    assert street and all(p.strength == "POSSIBLE" for p in street)
    _, nothing = _found(_page("Na Rua Sem Contexto, nº 12, ocorreu uma reunião.\n"))
    assert not nothing


def test_ocr_text_is_marked_as_ocr_evidence():
    proposals, _ = _found(_page("O imóvel objeto da ação fica na Rua Lida Por OCR, nº 9.\n", mode="OCR"))
    street = next(p for p in proposals if p.field == "street")
    assert street.evidence.method == "CONTEXT_BOUND_OCR_V2" and street.evidence.confidence == 0.91


def test_evidence_methods_are_closed_and_value_is_literal():
    for method in ("DOCUMENT_PATTERN_NATIVE_TEXT_V2", "CONTEXT_BOUND_OCR_V2"):
        PropertyEvidence("d", "a" * 64, "f.pdf", 1, "área privativa de 41,85 m²", method, None, "41,85")
    with pytest.raises(ValueError):
        PropertyEvidence("d", "a" * 64, "f.pdf", 1, "área privativa de 41,85 m²", "GUESSED_V2", None, "41,85")


def test_long_documents_stay_fast():
    from time import perf_counter
    # Pagina realista: ~3 mil caracteres, com virgulas e numeros que exercitam os padroes.
    body = ("Texto processual sintético, nº 12, sem relação com o imóvel; Rua citada em outro contexto, 45. " * 6 + "\n") * 5
    pages = [_page(body, number=index) for index in range(1, 251)]
    started = perf_counter()
    property_proposals("w", "d", "a" * 64, "autos.pdf", pages)
    assert perf_counter() - started < 10.0


def test_search_reuses_read_text_instead_of_reextracting(tmp_path):
    from scripts.backend_contract.application.case_document_texts import CaseDocumentText
    from scripts.backend_contract.application.property_record import GetPropertyProposals
    calls = []
    document = CaseDocumentText("11111111-1111-4111-8111-111111111111", "a" * 64, "autos.pdf", (_page("O imóvel objeto da ação fica na Rua Única Sintética, nº 1.\n"),), (), False)
    texts = SimpleNamespace(execute=lambda workspace: calls.append(workspace) or (document,))
    proposals = GetPropertyProposals(texts).execute("w")
    assert calls == ["w"] and {(p.field, p.value) for p in proposals} >= {("street", "Rua Única Sintética")}
    pending = GetPropertyProposals(SimpleNamespace(execute=lambda _w: (CaseDocumentText(document.content_id, "a" * 64, "autos.pdf", (), (), True),)))
    assert pending.execute("w") == () and pending.pending_documents("w") == ("autos.pdf",)


def test_label_proposal_ids_are_frozen_for_backup_replay():
    """Golden do nivel 1, calculado no V1 (main 3d3528e): mudar isto quebra backups antigos."""
    text = "Proprietário: A\r\nLogradouro: Rua X\x0cCEP: 50000-000\nÁrea privativa: 42,50 m²\n"
    proposals = property_proposals("w", "d", "a" * 64, "f.pdf", [_page(text)], include_legacy_labels=True)
    assert sorted((p.field, p.proposal_id) for p in proposals if p.evidence.method.endswith("_V1")) == [
        ("owner", "5bf486a68932dc3b5da1cd681c3efd15d48a50ca393e22a29644d3b9db535e8c"),
        ("postal_code", "92eb96105ebd6b52191c098edacf1fd3cc58e381baca3a98d04ecb02bff722ce"),
        ("private_area_m2", "81585efb915b11a22b03f3034b54f05306265675ecc22e930d8b0899576fa295"),
        ("street", "9e3682e60cfaeef24dd1e0b14b4b4e36fed03c0e9445fe0b41cdc8d427c2ca0b"),
    ]


def test_product_confirms_a_contextual_proposal_and_backup_replays_it(tmp_path):
    import json
    from pathlib import Path
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, _reseal, http_request
    from tests.test_property_record_v1 import _text_pdf
    runtime = build_local_api(tmp_path / "property-v2.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Imóvel em narrativa"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        pdf = _text_pdf([
            "FULANA SINTETICA, residente e domiciliada na Rua da Parte Sintetica, n. 45, Bairro Centro.",
            "A autora adquiriu o imovel objeto da acao, situado na Rua do Imovel Sintetico, n. 120.",
            "O imovel possui area privativa de 41,85 m2.",
        ])
        status, _ = _http(runtime, "POST", root + "/materials", raw_body=pdf, headers={"Content-Type": "application/pdf", "X-Document-Filename": "inicial.pdf"})
        assert status == 201
        status, found = _http(runtime, "GET", root + "/property-record/proposals")
        assert status == 200 and found["pending_documents"] == []
        values = {(p["field"], p["value"]) for p in found["proposals"]}
        assert ("street", "Rua do Imovel Sintetico") in values and ("private_area_m2", "41,85") in values and ("number", "120") in values
        assert not any(value == "Rua da Parte Sintetica" for _field, value in values)
        street = next(p for p in found["proposals"] if p["field"] == "street")
        assert street["strength"] == "STRONG" and street["evidence"]["method"] == "CONTEXT_BOUND_NATIVE_TEXT_V2"
        status, saved = _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": [{"field": "street", "value": street["value"], "proposal_id": street["proposal_id"]}]})
        assert status == 200 and saved["record"]["values"][0]["evidence"]["method"] == "CONTEXT_BOUND_NATIVE_TEXT_V2"
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        VerifyWorkspaceBackup().execute(backup)
        altered = json.loads(backup)
        revision = next(r for r in altered["artifact_revisions"] if r["artifact_kind"] == "PROPERTY_RECORD_V1")
        value = revision["payload"]["values"][0]
        value["value"] = value["evidence"]["source_value"] = "Rua Inventada"
        value["evidence"]["excerpt"] = value["evidence"]["excerpt"].replace("Rua do Imovel Sintetico", "Rua Inventada")
        with pytest.raises(RepositoryIntegrityError, match="property source evidence"):
            VerifyWorkspaceBackup().execute(_reseal(altered))
    finally:
        runtime.close()


# --- Revisao independente da PR #274: regressao do nivel 1 e vazamento de endereco de parte.


def test_owner_and_builder_labels_with_tax_ids_are_still_proposed():
    text = (
        "MATRÍCULA 12.345\n"
        "Proprietário: FULANO DE TAL SINTETICO, CPF 000.000.000-00\n"
        "Construtora: EMPRESA SINTETICA LTDA, CNPJ 00.000.000/0001-00\n"
        "Área privativa: 41,85 m²\n"
        "Data do habite-se: 10/03/2015\n"
    )
    _, found = _found(_page(text))
    assert {f for f, _ in found} >= {"owner", "construction_company", "private_area_m2", "habite_se_date"}


def test_explicit_property_address_label_survives_a_qualified_party_line():
    text = (
        "Vendedor: EMPRESA SINTETICA LTDA, CNPJ 00.000.000/0001-00, com sede na Rua da Sede, 1\n"
        "Comprador: FULANO SINTETICO, CPF 000.000.000-00, residente na Rua da Parte, 2\n"
        "Logradouro do imóvel: Rua do Imóvel Sintético\n"
        "Área privativa: 41,85 m²\n"
    )
    _, found = _found(_page(text))
    assert ("street", "Rua do Imóvel Sintético") in found and ("private_area_m2", "41,85") in found


def test_generic_address_label_after_party_qualification_is_not_proposed():
    text = "FULANO SINTETICO, residente e domiciliado em\nLogradouro: Rua da Parte Sintética\nCEP: 50000-000\n"
    _, found = _found(_page(text))
    assert not {f for f, _ in found} & {"street", "postal_code"}
    _, legacy = _found(_page(text), include_legacy_labels=True)
    assert ("street", "Rua da Parte Sintética") in legacy


@pytest.mark.parametrize("text", [
    # A. Abreviacao "Av." nao abre frase nova depois de "residente".
    "LAUDO\nFULANA SINTETICA, residente e domiciliada na Av. Boa Viagem Sintetica, nº 1500, Bairro Pina Sintetico, CEP 51011-000, requer.\n",
    # B. Timbre de advogado sem a palavra escritorio.
    "LAUDO\nRua do Sossego Sintetica, 120, Bairro Boa Vista Sintetica, Recife/PE - CEP 50050-080 - Tel (81) 0000-0000\n",
    # C. Cabecalho de juizo.
    "LAUDO\nPODER JUDICIÁRIO\nJUSTIÇA FEDERAL\nAv. Recife Sintetica, nº 6250, Bairro Jiquiá Sintetico, CEP 50865-900\n",
    # F. Patrono.
    "LAUDO\nPatrono: Dr. Beltrano Sintetico, Rua das Palmeiras Sinteticas, nº 45, Bairro Centro Sintetico, CEP 50000-000\n",
    # G. Precedente com "Rel. Des." antes da pista do imovel.
    "Nesse sentido (AC 0000000-00.0000.0.00.0000, Rel. Des. Fulano Sintetico), o imóvel situado na Rua X Sintetica, nº 10, Bairro Y Sintetico, foi avaliado.\n",
])
def test_party_counsel_court_and_precedent_addresses_never_become_property(text):
    _, found = _found(_page(text))
    assert not {f for f, _ in found} & {"street", "number", "neighborhood", "postal_code"}, found


def test_document_kind_does_not_leak_into_the_next_logical_piece():
    first = _page("LAUDO DE VISTORIA SINTETICO\nSem endereço nesta página.\n", number=1)
    second = _page("Petição sintética.\nA reunião ocorreu na Rua Qualquer Sintetica, 77, Bairro Sem Relação.\n", number=2)
    pieces = {1: "DOC-1", 2: "DOC-2"}
    proposals = property_proposals("w", "d", "a" * 64, "autos.pdf", [first, second], logical_document_for=pieces.get)
    assert not {p.field for p in proposals} & {"street", "neighborhood"}


def test_residential_adjective_and_neighbor_units_are_not_strong():
    _, found = _found(_page("O imóvel objeto da ação é de uso residencial unifamiliar, conforme a matrícula.\n"))
    assert not any(field == "development" for field, _ in found)
    proposals, _ = _found(_page("O imóvel objeto da ação, apartamento nº 302, fica ao lado do apartamento nº 101.\n"))
    units = [p for p in proposals if p.field == "unit"]
    assert units and all(p.strength == "POSSIBLE" for p in units)


def test_single_long_line_stays_linear():
    """Cada achado olha so a sua vizinhanca: o custo cresce com o texto, nao com o quadrado."""
    import time

    def elapsed(repeat):
        page = _page("LAUDO\n" + "apto 1 " * repeat)
        started = time.perf_counter()
        _found(page)
        return time.perf_counter() - started

    small, large = elapsed(2_000), elapsed(16_000)
    assert large < 8 * small * 2.5 and large < 10

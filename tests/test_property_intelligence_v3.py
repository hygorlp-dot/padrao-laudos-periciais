"""#288 — propostas do imóvel agrupadas por valor, com hierarquia documental.

Tudo sintético. Agrupar nunca promove: o perito continua escolhendo e
confirmando. Endereço de parte, advogado, juízo ou precedente continua fora.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.backend_contract.property_clusters import cluster_property_proposals, normalized_property_value
from scripts.backend_contract.property_record import property_proposals


def _page(text, number=1, mode="NATIVE_TEXT"):
    return SimpleNamespace(number=number, text=text, extraction_mode=SimpleNamespace(value=mode), confidence=None if mode == "NATIVE_TEXT" else 0.91)


def _proposals(*pages, document="d", pieces=None, filename="autos.pdf"):
    logical = (lambda number: pieces.get(number)) if pieces is not None else None
    return property_proposals("w", document, "a" * 64, filename, list(pages), logical_document_for=logical)


def _clusters(*proposal_sets):
    return cluster_property_proposals(tuple(item for group in proposal_sets for item in group))


def _field(clusters, field):
    return [cluster for cluster in clusters if cluster.field == field]


CONTRACT = "CONTRATO DE COMPRA E VENDA\nO imóvel objeto do contrato é o apartamento nº 01, Bloco 04, situado na Rua das Flores Sintéticas, nº 10, Bairro Sintético, Caruaru - PE, CEP 55000-000.\n"
PETITION = "PETIÇÃO INICIAL\nA autora adquiriu o imóvel objeto da ação, apartamento nº 1, Bloco 4, CEP 55000000, em Caruaru/PE.\n"


@pytest.mark.parametrize("field, left, right", [
    ("postal_code", "55000-000", "55000000"),
    ("state", "PE", "Pernambuco"),
    ("state", "pe", "PERNAMBUCO"),
    ("city", "Caruaru", "  CARUARU "),
    ("unit", "01", "1"),
    ("block", "04", "4"),
    ("private_area_m2", "42,50", "42.5"),
    ("contractual_value", "150.000,00", "150000"),
    ("habite_se_date", "05/03/2020", "2020-03-05"),
])
def test_safe_normalization_merges_the_same_value(field, left, right):
    assert normalized_property_value(field, left)[0] == normalized_property_value(field, right)[0]


@pytest.mark.parametrize("field, left, right", [
    ("street", "Rua 1", "Rua Um"),
    ("unit", "01A", "1A"),
    ("unit", "101", "11"),
    ("postal_code", "55000-000", "55000-001"),
    ("city", "Caruaru", "Carauru"),
    ("block", "A", "B"),
    ("development", "Residencial Sol", "Residencial Sol Nascente"),
])
def test_normalization_never_merges_different_values(field, left, right):
    assert normalized_property_value(field, left)[0] != normalized_property_value(field, right)[0]


def test_same_value_in_two_pieces_is_one_cluster_with_two_evidences():
    clusters = _clusters(_proposals(_page(CONTRACT, 1), _page(PETITION, 2), pieces={1: "DOC-CONTRATO", 2: "DOC-INICIAL"}))
    (unit,) = _field(clusters, "unit")
    assert unit.normalized_value == "1" and unit.source_count == 2 and unit.document_count == 2
    assert unit.display_value == "01" and unit.best_rank == "B"
    assert [e.source_rank for e in unit.evidences] == ["B", "E"]
    (postal,) = _field(clusters, "postal_code")
    assert postal.canonical_value == "55000-000" and postal.source_count == 2
    (state,) = _field(clusters, "state")
    assert state.canonical_value == "PE" and state.source_count == 2
    (city,) = _field(clusters, "city")
    assert city.display_value == "Caruaru" and city.confidence == "HIGH"


def test_city_and_state_come_from_city_dash_uf_only_for_the_subject_property():
    found = {(p.field, p.value) for p in _proposals(_page(CONTRACT))}
    assert ("city", "Caruaru") in found and ("state", "PE") in found
    for text in (
        "Fulana Sintética, residente e domiciliada na Rua X, nº 5, Caruaru - PE, CEP 55000-000.\n",
        "Advogado Sintético, OAB/PE 0000, com escritório na Rua Y, Recife - PE.\n",
        "Juízo da 1ª Vara Federal, Caruaru - PE.\n",
        "TRF5, Apelação Cível, Rel. Des. Fulano, imóvel localizado em Olinda - PE.\n",
        "Caruaru - PE, 10 de maio de 2024.\n",
        "o imóvel objeto da ação fica em caruaru - pe.\n",
    ):
        assert not {p.field for p in _proposals(_page(text))} & {"city", "state"}, text


def test_ranking_orders_matricula_contract_delivery_report_petition_and_possible():
    pages = {
        1: "MATRÍCULA Nº 0001 - REGISTRO DE IMÓVEIS\nImóvel: apartamento nº 101, unidade habitacional do Residencial Sintético.\n",
        2: "CONTRATO DE FINANCIAMENTO\nO imóvel objeto do contrato é o apartamento nº 102.\n",
        3: "TERMO DE ENTREGA\nEntrega da unidade habitacional apartamento nº 103.\n",
        4: "LAUDO TÉCNICO\nApartamento vistoriado: apartamento nº 104.\n",
        5: "PETIÇÃO INICIAL\nO imóvel objeto da ação é o apartamento nº 105.\n",
        6: "CONTESTAÇÃO\nO imóvel objeto da ação é o apartamento nº 106.\n",
        7: "DESPACHO\nO imóvel objeto da ação é o apartamento nº 107.\n",
    }
    proposals = _proposals(*(_page(text, number) for number, text in pages.items()), pieces={n: f"DOC-{n}" for n in pages})
    ranks = {p.value: p.source_rank for p in proposals if p.field == "unit"}
    assert ranks == {"101": "A", "102": "B", "103": "C", "104": "D", "105": "E", "106": "F", "107": "G"}
    units = _field(cluster_property_proposals(proposals), "unit")
    assert [c.display_value for c in units] == ["101", "102", "103", "104", "105", "106", "107"]
    # Sete valores fortes diferentes: conflito explícito, nenhum com confiança alta.
    assert all(c.confidence == "MEDIUM" for c in units)
    assert all(len(c.conflicting_cluster_ids) == 6 for c in units)


def test_possible_context_is_rank_h_and_low_confidence():
    proposals = _proposals(_page("O imóvel objeto da ação, apartamento nº 302, fica ao lado do apartamento nº 101.\n"))
    units = [p for p in proposals if p.field == "unit"]
    assert units and all(p.strength == "POSSIBLE" and p.source_rank == "H" for p in units)
    assert all(c.confidence == "LOW" for c in _field(cluster_property_proposals(proposals), "unit"))


def test_repeated_ten_times_is_one_cluster_and_never_outranks_the_registry():
    petitions = [_page("PETIÇÃO INICIAL\nO imóvel objeto da ação é o apartamento nº 202.\n", number) for number in range(1, 11)]
    registry = _page("MATRÍCULA Nº 0002 - REGISTRO DE IMÓVEIS\nImóvel: apartamento nº 201, unidade habitacional.\n", 11)
    proposals = _proposals(*petitions, registry, pieces={**{n: "DOC-INICIAL" for n in range(1, 11)}, 11: "DOC-MATRICULA"})
    units = _field(cluster_property_proposals(proposals), "unit")
    assert [(c.display_value, c.source_count, c.document_count) for c in units] == [("201", 1, 1), ("202", 10, 1)]
    # Ordem pela peça; divergência forte mantém ambos em confiança média.
    assert {c.confidence for c in units} == {"MEDIUM"}


def test_contract_petition_and_report_corroborate_without_auto_effect():
    pages = (
        _page("CONTRATO DE COMPRA E VENDA\nObjeto do contrato: unidade habitacional apartamento nº 303, Bloco 2.\n", 1),
        _page("PETIÇÃO INICIAL\nO imóvel objeto da ação, apartamento nº 303, Bloco 02.\n", 2),
        _page("LAUDO TÉCNICO\nApartamento vistoriado: apartamento nº 303, Bloco 2.\n", 3),
    )
    clusters = cluster_property_proposals(_proposals(*pages, pieces={1: "A", 2: "B", 3: "C"}))
    (unit,) = _field(clusters, "unit")
    (block,) = _field(clusters, "block")
    assert unit.document_count == 3 and unit.confidence == "HIGH" and unit.conflicting_cluster_ids == ()
    assert block.document_count == 3 and block.display_value == "2"
    # O cluster carrega as propostas originais: "Usar" grava uma delas, nunca um valor inventado.
    assert unit.display_value == unit.evidences[0].value


def test_party_address_never_joins_or_creates_a_subject_cluster():
    text = (
        "CONTRATO DE COMPRA E VENDA\n"
        "COMPRADORA: Fulana Sintética, residente e domiciliada na Rua Particular Sintética, nº 9, CEP 50000-111, Recife - PE.\n"
        "O imóvel objeto do contrato está situado na Rua das Flores Sintéticas, nº 10, CEP 55000-000, Caruaru - PE.\n"
    )
    clusters = cluster_property_proposals(_proposals(_page(text)))
    assert [c.display_value for c in _field(clusters, "postal_code")] == ["55000-000"]
    assert [c.display_value for c in _field(clusters, "city")] == ["Caruaru"]
    assert [c.display_value for c in _field(clusters, "street")] == ["Rua das Flores Sintéticas"]


def test_product_proposals_carry_clusters_with_rank_and_counts(tmp_path):
    from tests.test_process_participants_v1 import _import, _runtime
    from tests.test_product_integration_oracle_v1 import _http
    from tests.test_property_record_v1 import _text_pdf
    runtime = _runtime(tmp_path)
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Imóvel agrupado"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        _import(runtime, root, _text_pdf(["CONTRATO DE COMPRA E VENDA", "O imóvel objeto do contrato é o apartamento nº 01, Caruaru - PE, CEP 55000-000."]), "contrato.pdf")
        _import(runtime, root, _text_pdf(["PETIÇÃO INICIAL", "O imóvel objeto da ação é o apartamento nº 1, CEP 55000000."]), "inicial.pdf")
        status, body = _http(runtime, "GET", root + "/property-record/proposals")
        assert status == 200
        unit = next(c for c in body["clusters"] if c["field"] == "unit")
        assert unit["source_count"] == 2 and unit["document_count"] == 2 and unit["best_rank"] == "B"
        assert unit["display_value"] == "01" and unit["evidences"][0]["evidence"]["filename"] == "contrato.pdf"
        assert {e["source_rank"] for e in unit["evidences"]} == {"B", "E"}
        postal = next(c for c in body["clusters"] if c["field"] == "postal_code")
        assert postal["canonical_value"] == "55000-000" and postal["source_count"] == 2
        # Nada foi gravado.
        status, record = _http(runtime, "GET", root + "/property-record")
        assert status == 200 and record["record"]["values"] == []
    finally:
        runtime.close()

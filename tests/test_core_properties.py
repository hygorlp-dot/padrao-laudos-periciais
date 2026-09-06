import copy
from datetime import date, timedelta

from hypothesis import given, strategies as st

from scripts.extracao_pje.segmentar_documentos import segmentar_documentos
from scripts.motor_vicios.motor import _identidade_manifestacao
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.redacao_pericial.autocorrigir_redacao import autocorrigir
from scripts.redacao_pericial.datas import auditar_datas
from scripts.conhecimento_privado.pesquisa_online import buscar


def _pagina(numero):
    return {"pagina_pdf": numero, "possui_rodape_pje": False, "id_pje_detectado": None,
            "pagina_documento_detectada": None, "requer_ocr": False, "quantidade_caracteres": 10}


@given(st.integers(min_value=1, max_value=20))
def test_pje_cardinality_and_page_ownership_are_conserved(total):
    item = {"documento_id_interno": "DOC-PJE-001", "id_pje": "1", "ordem_indice": 1,
            "pagina_destino_link": 1, "titulo_original": "Documento", "pagina_inicial_informada": 1}
    segmentos = segmentar_documentos([item], [_pagina(i) for i in range(1, total + 1)])
    owned = [page for segment in segmentos for page in range(segment["pagina_pdf_inicio"], segment["pagina_pdf_fim"] + 1)]
    assert owned == list(range(1, total + 1))


@given(st.permutations([1, 2, 3, 4]))
def test_pje_segmentation_is_order_invariant(order):
    items = [{"documento_id_interno": f"DOC-PJE-{i:03d}", "id_pje": str(i), "ordem_indice": i,
              "pagina_destino_link": i, "titulo_original": f"Documento {i}", "pagina_inicial_informada": i}
             for i in order]
    pages = [_pagina(i) for i in range(1, 5)]
    result = segmentar_documentos(items, pages)
    assert [(x["documento_id"], x["pagina_pdf_inicio"]) for x in result] == [
        (f"DOC-PJE-{i:03d}", i) for i in range(1, 5)
    ]


@given(
    value=st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True)),
    unit=st.sampled_from(["cm", "%", "", "mm"]),
    qt=st.sampled_from(["QT-001", "QT-999"]),
)
def test_measurement_equivalence_fails_closed_for_missing_or_incompatible_data(value, unit, qt):
    plano = {"medicoes": [{"id": "MED-PLANO-001", "grandeza": "abertura de fissura", "local": "Sala",
                            "criterio": "resultado em mm", "questoes_tecnicas": ["QT-001"]}],
             "requisitos_cobertura": [{"questao_tecnica": "QT-001", "tipo": "MEDICAO",
                                        "obrigatoriedade": "OBRIGATORIA", "item_planejado": "MED-PLANO-001"}],
             "requisitos_semanticos": [{"requirement_id": "REQ-001-MED", "quesito": "QUE-001",
                                        "requisito": "Medir a abertura de fissura na Sala.",
                                        "itens_planejados": ["MED-PLANO-001"]}]}
    med = {"id": "MED-001", "grandeza": "umidade" if unit == "%" else "abertura de fissura",
           "valor": value, "unidade": unit, "local": "Sala", "questoes": [qt],
           "observacoes": ["OBS-001"], "metodo": "paquimetro"}
    vistoria = {"medicoes": [med], "cobertura": [{"tipo": "MEDICAO", "planejado": "MED-PLANO-001",
        "status": "SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE", "executado": [], "evidencia_equivalente": ["MED-001"],
        "equivalencia": {"requisito_original": "MED-PLANO-001", "tipo_evidencia": "MEDICAO",
                          "capability": "abertura de fissura", "metodo_substituto": "paquimetro"},
        "justificativa_equivalencia": "equivalencia rastreada"}]}
    result = recalcular_execucao(copy.deepcopy(plano), vistoria)
    if unit != "mm" or qt != "QT-001" or value is None or value != value or value in (float("inf"), float("-inf")):
        assert result["apto"] is False
    else:
        assert result["apto"] is True
        for field, replacement in (("unidade", "cm"), ("local", "Cobertura"), ("questoes", ["QT-999"]), ("observacoes", [])):
            mutated=copy.deepcopy(vistoria);mutated["medicoes"][0][field]=replacement
            assert recalcular_execucao(plano,mutated)["apto"] is False


@given(st.permutations(["OBS-001", "OBS-004", "OBS-009"]))
def test_motor_identity_is_invariant_to_observation_order(order):
    observations = [{"id": item} for item in order]
    assert _identidade_manifestacao(observations, ("fissura", "Sala")) == "001"


@given(st.dates(min_value=date(2000, 1, 1), max_value=date(2098, 12, 30)))
def test_redaction_date_fidelity_accepts_source_and_rejects_changed_digit(value):
    original = value.isoformat(); changed = (value + timedelta(days=1)).isoformat()
    assert auditar_datas(original, [original]) == []
    assert auditar_datas(changed, [original])[0]["tipo"] == "DATA_ALTERADA"


@given(st.sampled_from(["É importante destacar que ", "Cumpre ressaltar que ", "Vale salientar que "]))
def test_material_redaction_claim_is_byte_immutable_under_editorial_markers(prefix):
    text = prefix + "Conclusão técnica: 4,0 mm conforme NOR-001 em 11/08/2026."
    redaction = {"blocos": [{"pat_id": "PAT-001", "titulos": ["Conclusão"], "textos": [text], "claim_ids": ["CLM-001"]}],
                 "claims": [{"id": "CLM-001", "tipo": "CONCLUSAO_DE_QT", "texto_semantico": text, "imutavel": True}]}
    corrected, changes = autocorrigir(redaction, [{"tipo": "ABERTURA_GENERICA", "severidade": "EDITORIAL"}])
    assert corrected["blocos"][0]["textos"][0] == text
    assert corrected["claims"][0]["texto_semantico"] == text
    assert changes == []


@given(st.one_of(st.none(), st.text(min_size=0, max_size=20).filter(lambda x: x not in {"LOCAL_NO_EGRESS", "EXTERNAL_EGRESS"})))
def test_unknown_egress_capability_is_always_denied(capability):
    class Provider:
        def buscar(self, _): return []
    provider = Provider()
    if capability is not None:
        provider.EGRESS_CAPABILITY = capability
    try:
        buscar("fonte pública", provider)
    except PermissionError:
        pass
    else:
        raise AssertionError("provider desconhecido não pode egressar")

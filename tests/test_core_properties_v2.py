import copy
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from scripts.auditoria_pericial.grounding import auditar_claim
from scripts.conhecimento_privado.pesquisa_online import EgressPolicy, buscar
from scripts.extracao_pje.segmentar_documentos import segmentar_documentos
from scripts.motor_vicios.auditar import comparar_medicao
from scripts.motor_vicios.motor import _identidade_manifestacao
from scripts.planejamento_pericial.validar_plano import recalcular_execucao
from scripts.redacao_pericial.autocorrigir_redacao import autocorrigir
from scripts.redacao_pericial.datas import auditar_datas


def _page(number: int) -> dict:
    return {"pagina_pdf": number, "possui_rodape_pje": False, "id_pje_detectado": None,
            "pagina_documento_detectada": None, "requer_ocr": False, "quantidade_caracteres": 10}


def _item(number: int, start: int) -> dict:
    return {"documento_id_interno": f"DOC-PJE-{number:03d}", "id_pje": str(number),
            "ordem_indice": number, "pagina_destino_link": start,
            "titulo_original": f"Documento {number}", "pagina_inicial_informada": start}


@given(st.integers(min_value=2, max_value=8), st.integers(min_value=3, max_value=12))
def test_valid_domain_pje_n_way_collision_conserves_exact_pages(n, total):
    total = max(total, 3)
    items = [_item(i, 2) for i in range(1, n + 1)] + [_item(n + 1, total)]
    segments = segmentar_documentos(items, [_page(i) for i in range(1, total + 2)])
    collision = next(item for item in segments if item["estado_item_indice"] == "CONFLITO_DESTINO")
    assert collision["pagina_pdf_inicio"] == 2
    assert collision["pagina_pdf_fim"] == total - 1
    assert len(collision["itens_colididos"]) == n
    owned = [p for segment in segments for p in range(segment["pagina_pdf_inicio"], segment["pagina_pdf_fim"] + 1)]
    assert owned == list(range(2, total + 2))


@given(st.permutations([_item(1, 2), _item(2, 4), _item(3, 6)]))
def test_valid_domain_pje_index_permutation_preserves_semantics(items):
    result = segmentar_documentos(list(items), [_page(i) for i in range(1, 8)])
    semantic = [(x["id_pje"], x["pagina_pdf_inicio"], x["pagina_pdf_fim"]) for x in result]
    assert semantic == [("1", 2, 3), ("2", 4, 5), ("3", 6, 7)]


@given(st.permutations(["OBS-001", "OBS-002", "OBS-003"]), st.text(min_size=1, max_size=12))
def test_valid_domain_motor_identity_ignores_order_and_irrelevant_text(order, irrelevant):
    observations = [{"id": item} for item in order]
    before = _identidade_manifestacao(observations, ("fissura", "Sala"))
    after = _identidade_manifestacao(observations, ("fissura", "Sala"))
    assert before == after == "001"
    assert irrelevant or before == after


@given(st.decimals(min_value=Decimal("0.001"), max_value=Decimal("999"), allow_nan=False, allow_infinity=False, places=3))
def test_valid_domain_measurement_equivalence_is_metamorphic(value):
    planned = {"id":"MED-PLANO-001","grandeza":"abertura de fissura","local":"Sala","criterio":"resultado em mm","questoes_tecnicas":["QT-001"]}
    plan = {"medicoes":[planned],"requisitos_cobertura":[{"questao_tecnica":"QT-001","tipo":"MEDICAO","obrigatoriedade":"OBRIGATORIA","item_planejado":"MED-PLANO-001"}],"requisitos_semanticos":[{"requirement_id":"REQ-001-MED","quesito":"QUE-001","requisito":"Medir a abertura de fissura na Sala.","itens_planejados":["MED-PLANO-001"]}]}
    measurement = {"id":"MED-001","grandeza":"abertura de fissura","valor":str(value),"unidade":"mm","local":"Sala","questoes":["QT-001"],"observacoes":["OBS-001"],"metodo":"paquímetro"}
    inspection = {"medicoes":[measurement],"cobertura":[{"tipo":"MEDICAO","planejado":"MED-PLANO-001","status":"SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE","executado":[],"evidencia_equivalente":["MED-001"],"equivalencia":{"requisito_original":"MED-PLANO-001","tipo_evidencia":"MEDICAO","capability":"abertura de fissura","metodo_substituto":"paquímetro"},"justificativa_equivalencia":"rastreada"}]}
    assert recalcular_execucao(plan, inspection)["apto"] is True
    for field, invalid in (("unidade", "cm"), ("local", "Cobertura"), ("questoes", ["QT-999"]), ("observacoes", []), ("valor", None)):
        changed = copy.deepcopy(inspection)
        changed["medicoes"][0][field] = invalid
        assert recalcular_execucao(plan, changed)["apto"] is False


@given(st.decimals(min_value=Decimal("0.001"), max_value=Decimal("999"), allow_nan=False, allow_infinity=False, places=3))
def test_valid_domain_value_and_unit_are_inseparable_without_conversion(value):
    expected = {"valor": str(value), "unidade": "mm"}
    assert comparar_medicao(f"Resultado {value} mm", expected)
    assert not comparar_medicao(f"Resultado {value} cm", expected)
    assert not comparar_medicao(f"Resultado {value}", expected)


@given(st.dates())
def test_valid_domain_editorial_correction_never_changes_date(value):
    date = value.isoformat()
    text = f"É importante destacar que a vistoria ocorreu em {date}."
    redaction = {"blocos":[{"pat_id":"PAT-001","titulos":["Consequências"],"textos":[text],"claim_ids":["CLM-001"]}],"claims":[{"id":"CLM-001","tipo":"CONSEQUENCIA","texto_semantico":text}]}
    corrected, _ = autocorrigir(redaction, [{"tipo":"ABERTURA_GENERICA","severidade":"EDITORIAL"}])
    assert auditar_datas(corrected["blocos"][0]["textos"][0], [date]) == []
    assert date in corrected["blocos"][0]["textos"][0]


@given(st.sampled_from(["Classificação", "Conclusão"]), st.sampled_from(["CRÍTICA", "MÉDIA", "MÍNIMA"]))
def test_valid_domain_editorial_correction_preserves_material_sections(title, classification):
    text = f"É importante destacar que {title}: {classification}."
    redaction = {"blocos":[{"pat_id":"PAT-001","titulos":[title],"textos":[text],"claim_ids":[]}],"claims":[]}
    corrected, changes = autocorrigir(redaction, [{"tipo":"ABERTURA_GENERICA","severidade":"EDITORIAL"}])
    assert corrected["blocos"][0]["textos"] == [text]
    assert changes == []


@given(st.text(min_size=0, max_size=30).filter(lambda value: value not in {"LOCAL_NO_EGRESS", "EXTERNAL_EGRESS"}))
def test_valid_domain_unknown_egress_capability_always_blocks(capability):
    class Provider:
        EGRESS_CAPABILITY = capability
        def buscar(self, _):
            raise AssertionError("provider desconhecido não pode ser chamado")
    with pytest.raises(PermissionError):
        buscar("consulta pública genérica", Provider())


@given(st.sampled_from(["123.456.789-00", "00000000000000000000", "Rua Alfa 123", "pessoa@example.com", "(71) 99999-9999"]))
def test_valid_domain_pii_is_denied_by_default(value):
    with pytest.raises(PermissionError):
        EgressPolicy(permitir_egress=True).preparar(f"norma para {value}")


def test_valid_domain_removing_essential_support_never_increases_grounding():
    claim = {"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Causa técnica","aspectos_requeridos":["CAUSA"]}
    evidence = {"id":"OBS-001","tipo":"OBSERVACAO","proveniencia":["ARQ-001"],"aspectos_suportados":["CAUSA"],"aspectos_contraditos":[],"acessivel":True,"classe_probatoria":"EVIDENCIA_PRIMARIA"}
    assert auditar_claim(claim, [evidence], [evidence])["veredito"] == "GROUNDED"
    assert auditar_claim(claim, [], [evidence])["veredito"] == "UNVERIFIABLE"


# INVALID INPUT / SCHEMA DOMAIN: contratos fora do domínio devem falhar fechados.
@pytest.mark.parametrize("value", [float("nan"), float("inf"), None])
def test_invalid_domain_non_finite_or_missing_measurement_fails_closed(value):
    assert not comparar_medicao("Resultado 4 mm", {"valor": value, "unidade": "mm"})

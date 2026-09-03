"""#182 — cobertura de requisito material é decidida por VÍNCULO ESTRUTURADO a um
item planejado de TIPO APROPRIADO à natureza do requisito. Nunca por semelhança
textual, nunca por auto-injeção de texto, nunca por atividade genérica.

Relacional: "o quesito está ligado ao plano?"
Semântica: "todo requisito material do quesito tem destino verificável do tipo certo?"
apto exige as duas em 100% e zero requisitos não mapeados.
"""

import copy
import json
from pathlib import Path

from scripts.planejamento_pericial.validar_plano import recalcular_cobertura
from scripts.planejamento_pericial.requisitos_materiais import (
    classificar_requisito,
    extrair_requisitos_materiais,
    remover_ruido_estrutural,
)

ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return json.loads(
        (ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8")
    )


def _atv(id_, verificar="Verificar a condição alegada."):
    return {"id": id_, "verificar": verificar, "justificativa": "j", "questoes_tecnicas": ["QT-001"],
            "quesitos": ["QUE-001"], "alegacoes": [], "metodo": "Inspeção", "fundamentos": [],
            "evidencia_esperada": "registro", "obrigatoriedade": "OBRIGATORIA",
            "consequencia_se_nao_realizada": "limitação"}


def _med(id_):
    return {"id": id_, "grandeza": "abertura", "local": "parede", "motivo": "m",
            "instrumento_sugerido": "fissurômetro", "precisao_necessaria": None, "questoes_tecnicas": ["QT-001"],
            "quesitos": ["QUE-001"], "criterio": None, "obrigatoriedade": "OBRIGATORIA", "consequencia_ausencia": "c"}


def _plan_with(reqs, *, atividades=None, medicoes=None):
    plan = _plan()
    atividades = atividades if atividades is not None else [_atv("ATV-001")]
    medicoes = medicoes or []
    plan["atividades"] = atividades
    plan["medicoes"] = medicoes
    plan["cobertura"][0]["atividades"] = [a["id"] for a in atividades]
    plan["cobertura"][0]["medicoes"] = [m["id"] for m in medicoes]
    plan["requisitos_cobertura"] = (
        [{"questao_tecnica": "QT-001", "tipo": "ATIVIDADE", "obrigatoriedade": "OBRIGATORIA", "item_planejado": a["id"]} for a in atividades]
        + [{"questao_tecnica": "QT-001", "tipo": "MEDICAO", "obrigatoriedade": "OBRIGATORIA", "item_planejado": m["id"]} for m in medicoes]
    )
    plan["requisitos_semanticos"] = reqs
    return plan


def _r(rid, requisito, itens, classe=None, status=None):
    e = {"requirement_id": rid, "quesito": "QUE-001", "requisito": requisito, "itens_planejados": itens}
    if classe:
        e["classe"] = classe
    if status:
        e["status"] = status
    return e


# ---------------------------------------------------------------- classificação


def test_classificacao_por_natureza():
    assert classificar_requisito("Verificar a mancha de umidade aparente na parede.") == "INSPECAO"
    assert classificar_requisito("Caracterizar as manifestações alegadas.") == "INSPECAO"
    assert classificar_requisito("Aferir o teor de umidade da alvenaria.") == "MEDICAO"
    assert classificar_requisito("Verificar a espessura do contrapiso executado.") == "MEDICAO"
    assert classificar_requisito("Avaliar o recalque diferencial da fundação.") == "MEDICAO"
    assert classificar_requisito("Aferir o prumo e o nivelamento das paredes.") == "MEDICAO"
    assert classificar_requisito("Medir a abertura das fissuras sob carga.") == "MEDICAO"
    assert classificar_requisito("Solicitar o projeto executivo de impermeabilização.") == "DOCUMENTO"
    assert classificar_requisito("Juntar a planta com as dimensões dos ambientes.") == "DOCUMENTO"
    assert classificar_requisito("Solicitar o memorial de cálculo estrutural.") == "DOCUMENTO"


def test_classificacao_fail_closed():
    """Requisitos metrológicos fora de verbo óbvio NÃO caem em INSPECAO."""
    for texto in [
        "Verificar a resistência de aderência das placas cerâmicas.",
        "Verificar a estanqueidade da laje de cobertura.",
        "Avaliar a carbonatação do concreto armado dos pilares.",
        "Verificar a resistência mecânica do concreto estrutural.",
        "Avaliar o desempenho acústico das vedações verticais.",
    ]:
        assert classificar_requisito(texto) == "MEDICAO", texto
    # cláusula sem sinal de observação nem de medição -> INDETERMINADA (não INSPECAO)
    assert classificar_requisito("Avaliar as consequências técnicas pertinentes.") == "INDETERMINADA"
    assert classificar_requisito("Verificação técnica.") == "INDETERMINADA"


def test_verbo_de_requisicao_generico_e_modalidade_neutro():
    """P0 (revisões terminais 6b87d19): 'verificar'/'constatar'/'apontar'/'indicar'
    sozinhos NÃO estabelecem modalidade observacional. Requisito metrológico assim
    fraseado não pode chegar a INSPECAO nem, ponta a ponta, a apto=True."""
    corpus = [
        "Verificar as flechas das vigas do pavimento superior.",
        "Constatar se o piso está nivelado.",
        "Verificar se a laje está em nível.",
        "Apontar se o pavimento apresenta afundamento de trilha de roda.",
        "Constatar se as paredes estão aprumadas.",
        "Verificar se o revestimento está aderido.",
        "Verificar se a temperatura superficial está abaixo do ponto de orvalho.",
        "Verificar se a iluminância dos ambientes atende ao mínimo exigido.",
        "Verificar se as fissuras apresentam abertura superior a 0,3 mm.",
        "Verificar os desníveis do piso acabado.",
        "Apontar as cargas atuantes nas vigas.",
        "Indicar se há flecha excessiva nas vigas.",
    ]
    for texto in corpus:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_conector_existencial_e_modalidade_neutro():
    """P0 (PASS B contra 13e2bcf): 'há'/'existe'/'existência de' é tão
    modalidade-neutro quanto o verbo genérico — 'medir se há trinca > 0,3 mm'
    também usa 'há'. Substantivo metrológico fora do vocabulário de grandeza,
    fraseado com conector existencial, não pode virar INSPECAO nem apto=True."""
    corpus = [
        "Verificar se há afundamento de trilha de roda no pavimento.",
        "Constatar se há assentamento diferencial no piso.",
        "Verificar a existência de ondulação no piso de concreto.",
        "Constatar se há rebaixamento do lençol freático.",
        "Verificar se existe abaulamento do piso cerâmico.",
        "Constatar a presença de barriga na laje.",
        "Verificar se há flambagem do pilar metálico.",
        "Constatar se existe esmagamento do apoio de neoprene.",
        "Verificar se há folga excessiva na junta de dilatação.",
    ]
    for texto in corpus:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_fenomeno_qualificado_por_instrumento_e_medicao():
    """P0 (PASS A contra 13e2bcf): um fenômeno QUALIFICADO por termo instrumental
    ('umidade relativa do ar', 'potencial de corrosão da armadura') é medição, não
    observação a olho nu. _PATOLOGIA_ENSAIAVEL deixou de ter \\b morto após stem."""
    for texto in [
        "Verificar a umidade relativa do ar nos ambientes.",
        "Constatar a umidade relativa do ar e o ponto de orvalho.",
        "Verificar o potencial de corrosão da armadura das vigas.",
        "Verificar a corrosão das armaduras dos pilares.",
        "Constatar a perda de seção das barras de aço.",
        "Verificar a vibração excessiva na passarela metálica.",
    ]:
        assert classificar_requisito(texto) == "MEDICAO", texto


def test_esquadria_nao_e_sobre_bloqueada_como_medicao():
    """P2 (PASS A): 'esquadr' casava 'esquadrias' (componente construtivo, item
    de inspeção comum). Restrito a 'esquadro' (medição de esquadria)."""
    assert classificar_requisito("Descrever o estado de conservação das esquadrias.") == "INSPECAO"
    assert classificar_requisito("Verificar o esquadro dos vãos executados.") == "MEDICAO"


def test_controles_observacionais_nao_sao_sobre_bloqueados():
    """Contraparte do fail-closed: enquadramento genuinamente observacional
    (verbo de observação direta, marcador de existência/aparência, fenômeno
    visual) continua INSPECAO — o reparo do P0 não inutiliza o planejamento."""
    for texto in [
        "Constatar a existência de infiltração aparente.",
        "Verificar se há goteira visível no forro.",
        "Identificar revestimento destacado visualmente.",
        "Caracterizar as manifestações patológicas alegadas.",
        "Registrar fotograficamente o estado geral do imóvel.",
        "Descrever o padrão construtivo do imóvel.",
        "Localizar os pontos de infiltração na cobertura.",
        "Constatar a presença de mofo no banheiro.",
        "Apontar as manchas de umidade na laje.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto


def test_criterio_numerico_unicode_e_conectivo_portugues():
    """'≤'/'≥' são apagados por normalizar() (ascii-strip): recuperados sobre o
    texto cru. Conectivos comparativos em português também disparam MEDICAO."""
    for texto in [
        "Verificar a fissura com abertura ≤ 0,3 mm.",
        "Constatar se o desnível é ≥ 5 mm.",
        "Verificar a abertura inferior a 5 mm.",
        "Verificar a resistência no mínimo de 25 MPa.",
        "Constatar deslocamento de 5 mm na junta.",
        "Verificar a inclinação de 2%.",
    ]:
        assert classificar_requisito(texto) == "MEDICAO", texto


def test_indeterminada_exige_medicao_no_gate():
    r = recalcular_cobertura(_plan_with([_r("R1", "Avaliar as consequências técnicas pertinentes.", ["ATV-001"])]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


def test_gate_ignora_classe_persistida():
    """Uma classe MENTIROSA no plano não engana o gate: classe é re-derivada do texto."""
    r = recalcular_cobertura(_plan_with(
        [_r("R1", "Medir a abertura das fissuras sob carga estrutural.", ["ATV-001"], classe="INSPECAO", status="MAPEADO")]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


# ---------------------------------------------------------------- gate: matriz


def test_A_inspecao_com_atividade_apropriada():
    r = recalcular_cobertura(_plan_with([_r("R1", "Verificar a fissura da parede.", ["ATV-001"])]))
    assert r["cobertura_relacional"]["QUE-001"] is True
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is True
    assert (r["requisitos_materiais_cobertos"], r["total_requisitos_materiais"]) == (1, 1)
    assert r["cobertura_semantica_fracao"] == 1.0 and r["apto"] is True


def test_B_medicao_sem_medicao_planejada_fica_nao_mapeada():
    reqs = [_r(f"R{i}", t, ["ATV-001"]) for i, t in enumerate(
        ["Verificar a existência de fissuras.", "Constatar a infiltração aparente no forro.", "Registrar o estado do revestimento.",
         "Aferir a abertura das fissuras."])]
    r = recalcular_cobertura(_plan_with(reqs))
    assert r["cobertura_relacional"]["QUE-001"] is True
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert (r["requisitos_materiais_cobertos"], r["total_requisitos_materiais"]) == (3, 4)
    assert r["cobertura_semantica_fracao"] == 0.75 and r["apto"] is False


def test_C_atividade_generica_nao_cobre_requisito_de_medicao():
    r = recalcular_cobertura(_plan_with([
        _r("R1", "Inspecionar o imóvel de forma geral.", ["ATV-001"]),
        _r("R2", "Medir a estanqueidade da laje sob pressão.", ["ATV-001"]),
    ]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["requisitos_materiais_cobertos"] == 1 and r["apto"] is False


def test_medicao_com_medicao_planejada_e_coberta():
    r = recalcular_cobertura(_plan_with(
        [_r("R1", "Aferir a abertura das fissuras.", ["MED-PLANO-001"])],
        medicoes=[_med("MED-PLANO-001")]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is True and r["apto"] is True


def test_D_requisito_sem_destino_e_estado_legitimo():
    r = recalcular_cobertura(_plan_with([_r("R1", "Ensaiar a resistência do concreto.", [], status="NAO_MAPEADO")]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["requisitos_materiais_nao_mapeados"] == ["R1"] and r["apto"] is False


def test_J_extracao_indeterminada_e_rastreavel():
    r = recalcular_cobertura(_plan_with([_r("R1", "prova destrutiva", [], status="EXTRACAO_INDETERMINADA")]))
    assert "R1" in r["requisitos_materiais_nao_mapeados"] and r["apto"] is False


def test_K_quesito_nao_pertinente_fora_do_denominador():
    plan = _plan_with([_r("R1", "Verificar a fissura.", ["ATV-001"])])
    plan["requisitos_semanticos"].append({"requirement_id": "R9", "quesito": "QUE-999", "requisito": "x", "itens_planejados": []})
    r = recalcular_cobertura(plan)
    assert r["total_requisitos_materiais"] == 1 and r["apto"] is True


def test_L_status_bloqueado_permanece_com_requisito_nao_mapeado():
    plan = _plan_with([_r("R1", "Ensaiar concreto.", [])])
    plan["status"] = "BLOQUEADO_PARA_VISTORIA"
    r = recalcular_cobertura(plan)
    assert r["apto"] is False and r["requisitos_materiais_nao_mapeados"]


# ------------------------------------------------------------- mutation kills


def test_M1_apto_nao_ignora_cobertura_semantica():
    r = recalcular_cobertura(_plan_with([_r("R1", "Ensaiar concreto.", [])]))
    assert r["cobertura_relacional"]["QUE-001"] is True and r["apto"] is False


def test_M2_requisito_nao_mapeado_nao_e_descartado():
    r = recalcular_cobertura(_plan_with([
        _r("R1", "Verificar a fissura.", ["ATV-001"]),
        _r("R2", "Ensaiar concreto.", []),
    ]))
    assert r["total_requisitos_materiais"] == 2 and r["requisitos_materiais_nao_mapeados"] == ["R2"]


def test_M3_atividade_generica_com_todos_os_ids_nao_cobre_medicoes():
    reqs = [_r(f"R{i}", t, ["ATV-001"]) for i, t in enumerate(
        ["Verificar a fissura.", "Aferir a umidade higroscópica.", "Ensaiar a aderência cerâmica.", "Calcular o recalque diferencial."])]
    r = recalcular_cobertura(_plan_with(reqs))
    assert r["requisitos_materiais_cobertos"] == 1 and r["apto"] is False


def test_M4_extracao_vazia_nao_vira_cem_por_cento():
    q = {"id": "QUE-001", "pertinencia": "PERTINENTE_TECNICO",
         "texto_integral": "Num. 900001 - Pag. 1\nPagina complementar sem rodape", "materia_tecnica": "Num. 900001 - Pag. 1",
         "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert len(reqs) == 1 and reqs[0]["status"] == "EXTRACAO_INDETERMINADA"
    r = recalcular_cobertura(_plan_with([{**reqs[0]}]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


def test_M5_legacy_sem_requisitos_semanticos_nao_e_cem_por_cento():
    plan = _plan()
    plan.pop("requisitos_semanticos", None)
    r = recalcular_cobertura(plan)
    assert r["cobertura_relacional"]["QUE-001"] is True
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["requisitos_materiais_nao_mapeados"] == ["QUE-001:SEM_REQUISITOS_SEMANTICOS"]
    assert r["apto"] is False


# --------------------------------------------------------- false-green oracle


def test_false_green_text_injection_nao_converte_medicao_em_coberta():
    """Uma atividade cujo verificar contém o texto de um requisito de MEDIÇÃO,
    ainda que vinculada, NÃO cobre o requisito: a autoridade é o tipo do item."""
    atv = _atv("ATV-001", "Aferir a abertura das fissuras sob carga estrutural.")
    r = recalcular_cobertura(_plan_with([_r("R1", "Aferir a abertura das fissuras sob carga estrutural.", ["ATV-001"])], atividades=[atv]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


def test_generator_never_fabricates_semantic_coverage():
    fonte = (ROOT / "scripts/planejamento_pericial/gerar_plano.py").read_text(encoding="utf-8")
    assert 'verificar"] +=' not in fonte
    assert "Requisito do quesito:" not in fonte
    assert '"verificar":req["requisito"]' not in fonte and "'verificar':req['requisito']" not in fonte


def test_gate_nao_usa_similaridade_textual_como_autoridade():
    fonte = (ROOT / "scripts/planejamento_pericial/validar_plano.py").read_text(encoding="utf-8")
    for proibido in ("cosine", "embedding", "SequenceMatcher", "difflib", "similarity", "corresponde_requisito"):
        assert proibido not in fonte


# ------------------------------------------------------------ extraction: matriz


def test_H_ruido_estrutural_nao_vira_requisito():
    assert remover_ruido_estrutural("Existe umidade na parede? Num. 900001 - Pag. 1\nPagina complementar sem rodape") == "Existe umidade na parede?"
    q = {"id": "QUE-001", "texto_integral": "Verificar a fissura da parede. Num. 900123 - Pag. 4",
         "materia_tecnica": None, "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert all("900123" not in x["requisito"] and "Pag." not in x["requisito"] for x in reqs)
    assert any("fissura" in x["texto_normalizado"] for x in reqs)


def test_I_multiplas_clausulas_geram_multiplos_requisitos():
    q = {"id": "QUE-002", "materia_tecnica": "Verificar a existência de fissuras; avaliar a extensão do dano e estimar o custo do reparo.",
         "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-002"]}
    reqs = [x for x in extrair_requisitos_materiais(q) if x["status"] == "MATERIAL"]
    assert len(reqs) >= 3 and len({x["requirement_id"] for x in reqs}) == len(reqs)


def test_conjuncao_sem_verbo_nao_e_super_segmentada():
    q = {"id": "QUE-001", "materia_tecnica": "Medir a fissura da parede e a umidade do piso e o recalque da fundação.",
         "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [x for x in extrair_requisitos_materiais(q) if x["status"] == "MATERIAL"]
    assert len(reqs) == 1
    assert reqs[0]["classe"] == "MEDICAO"
    assert "umidade" in reqs[0]["requisito"] and "recalque" in reqs[0]["requisito"]


def test_E_requisitos_distintos_com_palavras_sobrepostas_nao_colapsam():
    q = {"id": "QUE-001", "materia_tecnica": "Caracterizar o acabamento superficial da laje. Documentar a geometria da laje.",
         "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [x for x in extrair_requisitos_materiais(q) if x["status"] == "MATERIAL"]
    assert len(reqs) == 2 and reqs[0]["requirement_id"] != reqs[1]["requirement_id"]


def test_F_clausula_identica_repetida_e_deduplicada():
    q = {"id": "QUE-001", "materia_tecnica": "Medir a fissura da parede. Medir a fissura da parede.",
         "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [x for x in extrair_requisitos_materiais(q) if x["status"] == "MATERIAL"]
    assert len(reqs) == 1


def test_G_reordenar_clausulas_preserva_identidade():
    base = "Medir a fissura da parede. Avaliar a umidade do piso."
    inv = "Avaliar a umidade do piso. Medir a fissura da parede."
    a = {x["texto_normalizado"]: x["requirement_id"] for x in extrair_requisitos_materiais(
        {"id": "QUE-001", "materia_tecnica": base, "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": []})}
    b = {x["texto_normalizado"]: x["requirement_id"] for x in extrair_requisitos_materiais(
        {"id": "QUE-001", "materia_tecnica": inv, "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": []})}
    assert a == b and len(a) == 2


def test_fragmento_curto_lider_nao_e_descartado():
    """Segmentação: um fragmento curto SEM predecessor funde ADIANTE, nunca some —
    senão um requisito de medição enxuto ('Flecha.') sumiria antes da parte
    observável e o quesito escaparia como só-inspeção."""
    q = {"id": "QUE-001", "materia_tecnica": "Flecha. Verificar a pintura das paredes.",
         "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [x for x in extrair_requisitos_materiais(q) if x["status"] == "MATERIAL"]
    assert any("flecha" in x["texto_normalizado"] for x in reqs)
    assert any(x["classe"] == "MEDICAO" for x in reqs)


def test_grupo_semantico_vazio_e_listado_em_nao_mapeados():
    """P2 (PASS A): 'requisitos_semanticos' presente mas SEM entrada para um quesito
    pertinente deixa rastro diagnóstico, não silêncio."""
    plan = _plan_with([])
    plan["requisitos_semanticos"] = []
    r = recalcular_cobertura(plan)
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert "QUE-001:GRUPO_SEMANTICO_VAZIO" in r["requisitos_materiais_nao_mapeados"]
    assert r["apto"] is False


def test_zero_material_requirements_falha_fechado():
    q = {"id": "QUE-001", "pertinencia": "PERTINENTE_TECNICO", "materia_tecnica": "   \n  ",
         "texto_integral": "  ", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert len(reqs) == 1 and reqs[0]["status"] == "EXTRACAO_INDETERMINADA"


# ---------------------------------------------------- os 4 REDs originais (V3)


def test_relational_links_do_not_claim_semantic_requirement_coverage():
    plan = _plan()
    plan["requisitos_semanticos"] = [{"quesito": "QUE-001", "requisito": "Verificar a estanqueidade da junta.", "itens_planejados": []}]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_each_semantic_requirement_needs_a_matching_planned_item():
    plan = _plan()
    plan["atividades"].append({**copy.deepcopy(plan["atividades"][0]), "id": "ATV-002", "verificar": "Verificar a existência da junta."})
    plan["cobertura"][0]["atividades"].append("ATV-002")
    plan["requisitos_cobertura"].append({"questao_tecnica": "QT-001", "tipo": "ATIVIDADE", "obrigatoriedade": "OBRIGATORIA", "item_planejado": "ATV-002"})
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Verificar a existência da junta.", "itens_planejados": ["ATV-002"]},
        {"quesito": "QUE-001", "requisito": "Conferir o isolamento acústico do painel.", "itens_planejados": []},
    ]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_topic_overlap_does_not_substitute_the_exact_requirement():
    plan = _plan()
    plan["atividades"][0]["verificar"] = "Inspecionar superficialmente a junta."
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Medir a estanqueidade da junta sob pressão controlada.", "itens_planejados": ["ATV-001"]}
    ]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_semantic_coverage_is_order_invariant():
    plan = _plan()
    plan["atividades"][0]["verificar"] = "Caracterizar o acabamento e registrar a geometria do elemento."
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Caracterizar o acabamento superficial.", "itens_planejados": ["ATV-001"]},
        {"quesito": "QUE-001", "requisito": "Registrar a geometria do elemento.", "itens_planejados": ["ATV-001"]},
    ]
    first = recalcular_cobertura(plan)
    plan["requisitos_semanticos"].reverse()
    second = recalcular_cobertura(plan)
    assert first == second
    assert first["cobertura_requisitos_semanticos"]["QUE-001"] is True and first["apto"] is True

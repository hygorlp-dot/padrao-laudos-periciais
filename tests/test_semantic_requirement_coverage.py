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
    evidencia_requerida,
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


def test_metamorphic_objeto_tecnico_desconhecido_nunca_vira_inspecao():
    """PROPRIEDADE OPEN-WORLD (obrigatória): objeto técnico NUNCA visto +
    nenhuma prova explícita de que observação basta (visível/aparente/a olho nu/
    fotográfico/fenômeno visual conhecido) ⇒ NUNCA INSPECAO. Na dúvida →
    INDETERMINADA (estrito). Deve valer para substantivos artificiais."""
    verbos = ["Verificar", "Constatar", "Avaliar", "Registrar", "Descrever",
              "Caracterizar", "Localizar", "Observar", "Apontar", "Analisar", "Determinar"]
    conectores = ["o {n} do elemento", "se há {n} no componente", "a existência de {n} na peça",
                  "o {n} medido na seção", "o parâmetro {n} da camada", "o índice {n} do apoio"]
    objetos = ["zeta", "lambda", "omega", "phi", "ksi", "qplex", "vortan", "delta-kappa",
               "sigma-r", "grau theta", "fator wz", "resposta upsilon"]
    combos = [f"{v} {c.format(n=n)}." for v in verbos for c in conectores for n in objetos]
    for texto in combos:
        assert classificar_requisito(texto) != "INSPECAO", texto
    # amostra ponta a ponta: atividade genérica + zero medição ⇒ NÃO apto
    for texto in combos[::37]:
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["cobertura_efetiva"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_metamorphic_objeto_desconhecido_com_prova_visual_e_inspecao():
    """Contraparte: o MESMO objeto artificial, quando há prova explícita de
    modalidade observacional (qualificador visual), é INSPECAO — a propriedade
    open-world nega o default, não a evidência positiva."""
    for texto in [
        "Registrar a mancha de zeta visível na parede.",
        "Fotografar a fissura de lambda na viga.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto
    # V11 (P0-A2-1): contabilidade observacional INTEGRAL — "aspecto omega" é
    # token de conteúdo NÃO contabilizado (objeto desconhecido): sobre-bloqueio
    # seguro documentado, nunca falso-verde.
    assert classificar_requisito("Descrever o padrão construtivo com aspecto omega aparente.") == "INDETERMINADA"


def test_verbo_de_observacao_direta_exige_objeto_descritivo():
    """P0 (PASS A+B contra 45f93da): 'registrar'/'descrever'/'caracterizar'/
    'localizar'/'observar'/'vistoriar' são modalidade-neutros QUANTO AO OBJETO —
    'registrar o assentamento diferencial' exige nivelamento topográfico. Sem
    objeto descritivo-qualitativo → INDETERMINADA, e não pode virar apto=True."""
    corpus = [
        "Registrar a velocidade de corrosão das barras de aço da laje.",
        "Descrever a resistividade elétrica do concreto de cobrimento.",
        "Registrar o potencial eletroquímico das armaduras da cortina.",
        "Registrar o cobrimento das armaduras das vigas.",
        "Registrar a queda de tensão na alimentação dos quadros.",
        "Registrar o assentamento diferencial observado nas fundações.",
        "Caracterizar a deriva de topo do edifício sob vento.",
        "Localizar a região de maior tensão na laje.",
        "Observar a folga entre o batente e a folha da porta.",
        "Descrever a conicidade do pilar circular.",
        "Vistoriar o afundamento de trilha de roda no pavimento.",
        "Registrar a rotação da fundação isolada.",
        "Registrar a umidade na parede da fachada.",
        "Descrever a ovalização da tubulação metálica.",
    ]
    for texto in corpus:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def _vistoria_exec(*planejados):
    return {
        "cobertura": [{"planejado": p, "status": "EXECUTADO", "executado": [f"{p}-EXEC"]} for p in planejados],
        "atividades_executadas": [{"id": f"{p}-EXEC", "atividade_planejada": p, "questoes_tecnicas": ["QT-001"]}
                                  for p in planejados if p.startswith("ATV")],
        "medicoes": [{"id": f"{p}-EXEC", "medicao_planejada": p, "questoes": ["QT-001"]}
                     for p in planejados if p.startswith("MED")],
    }


def test_recalcular_execucao_A_medicao_sem_destino_executado_nao_e_apto():
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras sob carga.", ["ATV-001"])])
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
    assert res["apto"] is False
    assert any("REQUISITO_SEMANTICO" in str(f.get("motivo", "")) for f in res["faltantes"])


def test_recalcular_execucao_B_classe_persistida_mentirosa_e_ignorada():
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([_r("R1", "Medir a estanqueidade da laje sob pressão.", ["ATV-001"],
                           classe="INSPECAO", status="MAPEADO")])
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
    assert res["apto"] is False


def test_recalcular_execucao_C_item_de_tipo_errado_nao_satisfaz_medicao():
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([_r("R1", "Ensaiar a resistência do concreto estrutural.", ["ATV-001"])])
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
    assert res["apto"] is False
    assert any("NAO_EXECUTADO" in str(f.get("motivo", "")) or "NAO_MAPEADO" in str(f.get("motivo", ""))
               for f in res["faltantes"])


def test_recalcular_execucao_D_semanticos_vazios_nao_fabricam_completude():
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([])
    plano["requisitos_semanticos"] = []
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
    assert res["apto"] is False


def test_recalcular_execucao_E_medicao_executada_satisfaz():
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras.", ["MED-PLANO-001"])],
                       medicoes=[_med("MED-PLANO-001")])
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001", "MED-PLANO-001"))
    assert not any("REQUISITO_SEMANTICO" in str(f.get("motivo", "")) for f in res["faltantes"])


def test_controles_observacionais_nao_sao_sobre_bloqueados():
    """Contraparte do fail-closed: enquadramento genuinamente observacional
    (verbo de observação direta, marcador de existência/aparência, fenômeno
    visual) continua INSPECAO — o reparo do P0 não inutiliza o planejamento."""
    for texto in [
        "Constatar a existência de infiltração aparente.",
        "Verificar se há goteira visível no forro.",
        "Caracterizar as manifestações patológicas alegadas.",
        "Registrar fotograficamente o estado geral do imóvel.",
        "Descrever o padrão construtivo do imóvel.",
        "Constatar a presença de mofo no banheiro.",
        "Apontar as manchas de umidade na laje.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto
    # V11 (P0-A2-1): "pontos de infiltração" — "pontos" é token de conteúdo não
    # contabilizado (o fenômeno está em de-complemento, não é o head da demanda):
    # sobre-bloqueio seguro documentado (INDETERMINADA → medição estrita).
    assert classificar_requisito("Localizar os pontos de infiltração na cobertura.") == "INDETERMINADA"


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
        _r("R1", "Inspecionar as fissuras aparentes do imóvel.", ["ATV-001"]),
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
    plan["atividades"][0]["verificar"] = "Caracterizar o acabamento e registrar as manchas do elemento."
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Caracterizar o acabamento superficial.", "itens_planejados": ["ATV-001"]},
        {"quesito": "QUE-001", "requisito": "Registrar as manchas do elemento.", "itens_planejados": ["ATV-001"]},
    ]
    first = recalcular_cobertura(plan)
    plan["requisitos_semanticos"].reverse()
    second = recalcular_cobertura(plan)
    assert first == second
    assert first["cobertura_requisitos_semanticos"]["QUE-001"] is True and first["apto"] is True


def test_verbo_fotografar_nao_e_prova_de_objeto():
    """P0 (PASS A contra 41dd08f): o ramo de marcador visual casava o VERBO
    'fotografar' e concedia INSPECAO sem nenhuma prova de objeto — 'fotografar o
    parâmetro omega' chegava a apto=True com atividade genérica e zero medição.
    Verbo/marcador de MODO nunca decide INSPECAO: toda concessão exige prova
    positiva NO OBJETO (fenômeno visual conhecido ou objeto descritivo-qualitativo).
    """
    corpus = [
        "Fotografar o parâmetro omega do apoio.",
        "Fotografar o índice zeta estrutural.",
        "Fotografar o coeficiente lambda do componente.",
        "Fotografar a resposta phi do elemento.",
        "Fotografar o gradiente ksi da camada.",
        "Fotografar a velocidade de corrosão das armaduras.",
        "Fotografar a resistividade elétrica do concreto.",
        "Fotografar o potencial eletroquímico das armaduras.",
        "Fotografar o assentamento diferencial da fundação.",
        "Fotografar a deriva de topo do edifício.",
        "Fotografar a ovalização da tubulação.",
        "Fotografar a conicidade do pilar.",
    ]
    for texto in corpus:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_area_de_fenomeno_e_medicao():
    """P1 (PASS B contra 41dd08f): um lookahead não declarado em
    _GRANDEZA_DIMENSIONAL excluía 'área de infiltração/mancha/fissura/...' do gate
    de medição, derrubando essas frases para INSPECAO (satisfazível por atividade
    genérica). 'Área de <fenômeno>' é EXTENSÃO quantificada -> MEDICAO, como no
    parent 45f93da (a exceção é revertida, não refinada)."""
    for texto in [
        "Verificar a área de infiltração na parede do banheiro.",
        "Verificar a área de mancha na fachada norte.",
        "Constatar a área de fissuração na laje.",
        "Verificar a área de descolamento do revestimento cerâmico.",
    ]:
        assert classificar_requisito(texto) == "MEDICAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["apto"] is False, texto


def test_fenomeno_incidental_em_pp_locativo_nao_absolve_objeto_desconhecido():
    """P0-A2-1 (PASS A2 contra f0b3249): fenômeno observável citado DENTRO de PP
    locativo ("junto às fissuras", "próximo à mancha") ou coordenado a um objeto
    metrológico/desconhecido absolvia a demanda inteira — prova_objeto casava
    _FENOMENO_OBSERVAVEL em qualquer posição e concedia INSPECAO, chegando a
    apto=True (planning E execução) com atividade genérica e zero medição.

    Reparo de AUTORIDADE (V11): a concessão de INSPECAO exige CONTABILIDADE
    OBSERVACIONAL INTEGRAL da demanda — PP locativo é removido por inteiro (seu
    conteúdo não conta), NPs observacionais são consumidos com seus
    de-complementos, e qualquer token de conteúdo residual derruba a cláusula
    para INDETERMINADA. UNKNOWN NEVER BECOMES INSPECAO EFFECTIVE."""
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    corpus = [
        "Verificar o cobrimento das armaduras junto às fissuras.",
        "Verificar o espaçamento das fissuras.",
        "Verificar o parâmetro omega próximo à mancha.",
    ]
    for texto in corpus:
        assert classificar_requisito(texto) == "INDETERMINADA", texto
        plano = _plan_with([_r("R1", texto, ["ATV-001"])])
        r = recalcular_cobertura(plano)
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto
        res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
        assert res["apto"] is False, texto


def test_contabilidade_observacional_preserva_inspecao_legitima():
    """Contraparte do P0-A2-1: a contabilidade integral NÃO sobre-bloqueia o
    enquadramento genuinamente observacional — head de fenômeno com
    de-complemento e PP locativo removido, objeto descritivo com verbo/modo de
    observação, marcador visual como qualificador do NP."""
    for texto in [
        "Verificar a mancha de umidade aparente na parede.",
        "Fotografar a fissura de lambda na viga.",
        "Constatar a presença visível de infiltração.",
        "Registrar fotograficamente o estado aparente da fachada.",
        "Verificar se há goteira visível no forro.",
        "Apontar as manchas de umidade na laje.",
        "Descrever o estado de conservação das esquadrias.",
        "Caracterizar o acabamento superficial.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto


def test_coordenacao_nao_absolve_objeto_desconhecido():
    """V11: a coordenação é contabilizada por inteiro — um fenômeno observável
    coordenado a um objeto desconhecido NÃO absolve o objeto desconhecido."""
    for texto in [
        "Verificar a fissura e o parâmetro omega do apoio.",
        "Registrar as manchas e o cobrimento das armaduras.",
    ]:
        assert classificar_requisito(texto) == "INDETERMINADA", texto


def test_vinculo_semantico_e_re_derivado_do_item_nao_da_cobertura_editavel():
    """P1-A2-2 (PASS A2): 'vinculados' era lido de cobertura[quesito] — uma
    medição ESTRANGEIRA ao quesito (quesitos=['QUE-999'], questoes_tecnicas=
    ['QT-999']) listada à força em cobertura[QUE-001].medicoes fabricava apto
    no planning e na execução. O vínculo passa a ser RE-DERIVADO do item: ele
    só conta se existir E (qid ∈ item.quesitos OU item.questoes_tecnicas
    intersecta as questões técnicas da cobertura do quesito)."""
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    estrangeira = {**_med("MED-999"), "questoes_tecnicas": ["QT-999"], "quesitos": ["QUE-999"]}
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras.", ["MED-999"])], medicoes=[estrangeira])
    # isola a camada semântica: sem a linha relacional da medição
    plano["requisitos_cobertura"] = [r for r in plano["requisitos_cobertura"] if r["tipo"] != "MEDICAO"]
    r = recalcular_cobertura(plano)
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert "R1" in r["requisitos_materiais_nao_mapeados"] and r["apto"] is False
    vistoria = _vistoria_exec("ATV-001", "MED-999")
    vistoria["medicoes"][0]["questoes"] = ["QT-999"]
    assert recalcular_execucao(plano, vistoria)["apto"] is False


def test_recheck_da_redacao_preserva_cobertura_e_detecta_nao_mapeados():
    """P2c (PASS B2): _plano_para_recheck descartava a chave 'cobertura' — o
    recálculo no recheck da redação não via os quesitos do plano e NÃO detectava
    requisitos_materiais_nao_mapeados (cobertura semântica fingia completude)."""
    from scripts.motor_vicios.pipeline import _plano_para_recheck
    plano = _plan_with([_r("R1", "Ensaiar concreto.", [])])
    recheck = _plano_para_recheck(plano)
    assert "cobertura" in recheck
    r = recalcular_cobertura(recheck)
    assert r["requisitos_materiais_nao_mapeados"] == ["R1"] and r["apto"] is False


def test_pp_locativo_nao_atravessa_coordenacao_v12():
    """P0 (PASS A3 contra 00bf26b, SAME_CLASS_SURVIVED): _PP_LOCATIVO tinha
    fronteira de parada assimétrica (só ' e ' ou fim de string) — coordenação
    com 'ou'/vírgula fazia o PP locativo engolir um objeto coordenado
    desconhecido até o fim da string. A demanda agora é partida em cláusulas
    ANTES de qualquer remoção (mesmo conector de _segmentar); cada cláusula é
    contabilizada isoladamente e TODAS precisam resolver para INSPECAO."""
    for texto in [
        "Registrar a fissura no forro ou o parâmetro omega.",
        "Examinar a mancha aparente na fachada ou o assentamento diferencial.",
        "Fotografar a fissura no forro ou o parâmetro omega da estrutura.",
        "Constatar a existência de fissura no local ou o coeficiente lambda.",
        "Registrar a fissura no forro, o parâmetro omega da estrutura.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_de_complemento_desconhecido_sem_prova_de_modo_e_indeterminada_v12():
    """P0 (PASS B3 contra 00bf26b, SAME_CLASS_SURVIVED): o de-complemento 'de X'
    do NP observacional era IRRESTRITO — qualquer palavra virava prova de
    objeto por forma sintática, sem checagem de conteúdo ('a fissura DO ZETA').
    Reproduzido ponta a ponta via gerar_plano.gerar() pelo revisor: mapeado para
    atividade genérica auto-gerada, zero medição, apto=True. O de-complemento
    aberto só é absorvido quando há prova de modo/suficiência visual explícita
    em algum ponto da demanda (mesmo sinal `modo_observacional`); sem essa
    prova, um substantivo fora do vocabulário fechado permanece resíduo."""
    for texto in [
        "Verificar a fissura do zeta.",
        "Verificar a fissura do zeta do omega do lambda do phi do sigma.",
        "Constatar a existência da mancha do parâmetro omega.",
        "Avaliar o cobrimento das armaduras do apoio zeta.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_de_complemento_seguro_e_aberto_com_modo_continuam_inspecao_v12():
    """Contraparte positiva do V12: complemento de elemento/local construtivo
    conhecido ('da parede') continua absorvido sem exigência adicional; e um
    de-complemento desconhecido, quando a demanda tem prova de modo/suficiência
    visual explícita em qualquer ponto (verbo de observação direta ou
    marcador visual), continua INSPECAO — a propriedade open-world nega o
    default, não a evidência positiva (mesmo princípio do teste metamórfico)."""
    for texto in [
        "Verificar a fissura da parede.",
        "Registrar a mancha da fachada.",
        "Fotografar a fissura de lambda na viga.",
        "Registrar a mancha de zeta visível na parede.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto


def test_vinculo_nao_sobreposto_por_qt_compartilhada_entre_quesitos_v12():
    """P0 (PASS A3+B3 contra 00bf26b, SAME_CLASS_SURVIVED): a re-derivação
    'qid ∈ item.quesitos OU QT ∩ QT' do V11 ainda deixava a declaração
    explícita do item ser SOBREPOSTA por questão técnica incidentalmente
    compartilhada — um item honestamente declarado a OUTRO quesito
    (quesitos=['QUE-999']), mas cuja questão técnica também é relevante para
    QUE-001 (reuso legítimo de QT entre quesitos distintos), era creditado a
    QUE-001 mesmo assim. Para tipos com campo `quesitos` no schema
    (atividade/medicao/fotografia), a declaração do item é autoridade ÚNICA —
    nunca sobreposta nem complementada por QT."""
    estrangeira = {**_med("MED-PLANO-999"), "quesitos": ["QUE-999"]}  # QT-001 preservada de propósito
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras.", ["MED-PLANO-999"])],
                       medicoes=[estrangeira])
    plano["requisitos_cobertura"] = [x for x in plano["requisitos_cobertura"] if x["tipo"] != "MEDICAO"]
    r = recalcular_cobertura(plano)
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert "R1" in r["requisitos_materiais_nao_mapeados"] and r["apto"] is False
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    vistoria = {
        "cobertura": [{"planejado": "ATV-001", "status": "EXECUTADO", "executado": ["ATV-001-EXEC"]},
                      {"planejado": "MED-PLANO-999", "status": "EXECUTADO", "executado": ["MED-999-EXEC"]}],
        "atividades_executadas": [{"id": "ATV-001-EXEC", "atividade_planejada": "ATV-001", "questoes_tecnicas": ["QT-001"]}],
        "medicoes": [{"id": "MED-999-EXEC", "medicao_planejada": "MED-PLANO-999", "questoes": ["QT-001"]}],
    }
    assert recalcular_execucao(plano, vistoria)["apto"] is False


def test_vinculo_ignora_cobertura_adulterada_quando_item_declara_outro_quesito_v12():
    """Variante A do P0 acima: adulterar cobertura[quesito].questoes_tecnicas
    diretamente (lista editável) não muda o resultado — um item que declara
    explicitamente pertencer a outro quesito nunca é creditado, qualquer que
    seja o conteúdo de cobertura[]."""
    estrangeira = {**_med("MED-999"), "questoes_tecnicas": ["QT-999"], "quesitos": ["QUE-999"]}
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras.", ["MED-999"])], medicoes=[estrangeira])
    plano["requisitos_cobertura"] = [x for x in plano["requisitos_cobertura"] if x["tipo"] != "MEDICAO"]
    plano["cobertura"][0]["questoes_tecnicas"] = ["QT-999"]  # adulteração da lista editável
    r = recalcular_cobertura(plano)
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


def test_verbo_observacao_direta_generico_nao_libera_complemento_aberto_v121():
    """P0 (PASS B4 contra daaceac, SAME_CLASS_SURVIVED): o V12 usava o mesmo
    sinal `modo_observacional` (verbo de observação direta OU marcador visual)
    para liberar o de-complemento ABERTO — mas o próprio módulo já documenta
    esses verbos (registrar/descrever/caracterizar/localizar/observar/
    inspecionar/examinar) como MODALIDADE-NEUTROS quanto ao objeto. Usá-los
    para justificar o objeto do complemento contradizia essa premissa:
    'registrar a fissura DO ZETA' não prova que 'zeta' seja observável só
    porque 'registrar' é verbo de observação direta. Só marcador visual
    EXPLÍCITO (_MARCADOR_VISUAL — inclui 'fotografar', definicionalmente um
    ato visual) libera o complemento aberto; o verbo genérico sozinho não."""
    for texto in [
        "Registrar a fissura do zeta.",
        "Descrever a fissura do zeta.",
        "Caracterizar a fissura do zeta.",
        "Localizar a fissura do zeta.",
        "Observar a fissura do zeta.",
        "Inspecionar a fissura do zeta.",
        "Examinar a fissura do zeta.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_marcador_visual_nao_vaza_entre_clausulas_coordenadas_v121():
    """P0 (PASS A4+B4 contra daaceac, SAME_CLASS_SURVIVED): o sinal habilitador
    (verbo de observação direta / marcador visual) era calculado uma única vez
    sobre o texto INTEIRO da demanda e aplicado a TODAS as cláusulas — um
    marcador em uma cláusula coordenada liberava o de-complemento aberto em
    OUTRA cláusula sem marcador próprio. Cada cláusula agora recalcula seu
    próprio sinal habilitador; o verbo inicial só é reintegrado à primeira
    cláusula (a única que efetivamente o tinha)."""
    for texto in [
        "Fotografar a mancha e a fissura do zeta.",
        "Registrar a fissura, a mancha do zeta.",
        "Fotografar a mancha e a fissura do lambda.",
        "Fotografar a mancha de umidade e a fissura do encunhamento das vigas.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_pp_locativo_bounded_fecha_coordenadores_nao_enumerados_v121():
    """P0 (PASS A4 contra daaceac, SAME_CLASS_SURVIVED): partir cláusulas por
    _CONECTOR não cobre todo coordenador de português pericial ('bem como',
    'assim como', 'além de', '/', parênteses, travessão) — dentro da MESMA
    cláusula, o PP locativo sem limite (.* até o fim) reabria exatamente o
    vazamento original por qualquer coordenador não enumerado. O PP locativo
    agora é limitado a um punhado de palavras (NP locativo real é curto) —
    fecha a classe inteira de coordenadores sem precisar enumerá-los."""
    for texto in [
        "Verificar a fissura na parede bem como o parametro omega.",
        "Verificar a fissura na parede alem do parametro omega.",
        "Verificar a fissura na parede assim como o coeficiente lambda.",
        "Verificar a fissura na parede tanto quanto o parametro omega.",
        "Verificar a fissura na parede (o parametro omega).",
        "Verificar a fissura na parede - o parametro omega.",
        "Verificar a fissura na parede / o parametro omega.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_fotografar_e_marcador_visual_definicional_continua_liberando_v121():
    """Contraparte positiva do V12.1: 'fotografar' continua suficiente SOZINHO
    para liberar o complemento aberto (está em _MARCADOR_VISUAL — é
    definicionalmente um ato visual/fotográfico, distinto de
    'registrar'/'descrever'/etc, que são verbos de documentação genéricos sem
    garantia de modalidade). Não há regressão da contraparte metamórfica
    positiva pré-existente."""
    for texto in [
        "Fotografar a fissura de lambda na viga.",
        "Fotografar a fissura do zeta.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto


def test_marcador_de_modo_sem_prova_de_objeto_e_sobre_bloqueio_seguro():
    """SAFE_OVERBLOCKING != FALSE_GREEN: no funil, qualificador de modo
    ('visualmente', 'fotograficamente', ...) sem fenômeno visual conhecido nem
    objeto descritivo-qualitativo NÃO decide INSPECAO -> INDETERMINADA (estrito).
    Caso de recall medido separadamente, aceito como sobre-bloqueio seguro."""
    assert classificar_requisito("Identificar revestimento destacado visualmente.") == "INDETERMINADA"


def test_execucao_semantica_status_mentiroso_nao_satisfaz():
    """P1 (PASS A+B contra 41dd08f): a camada semântica de execução confiava no
    STATUS persistido da vistoria (EXECUTADO/SUBSTITUIDO) sem exigir artefato —
    status mentiroso com executado=[] fabricava apto=True. Status NÃO é
    autoridade: a execução efetiva exige artefato com back-reference ao item
    planejado ou equivalência válida, o mesmo critério do caminho relacional."""
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([_r("R1", "Aferir a abertura das fissuras sob carga.", ["MED-PLANO-001"])],
                       medicoes=[_med("MED-PLANO-001")])
    # obrigação relacional da medição removida: só a camada semântica protege
    plano["requisitos_cobertura"] = [r for r in plano["requisitos_cobertura"] if r["tipo"] != "MEDICAO"]
    base = {"cobertura": [{"planejado": "ATV-001", "status": "EXECUTADO", "executado": ["ATV-001-EXEC"]}],
            "atividades_executadas": [{"id": "ATV-001-EXEC", "atividade_planejada": "ATV-001",
                                       "questoes_tecnicas": ["QT-001"]}],
            "medicoes": []}
    mentirosa_exec = copy.deepcopy(base)
    mentirosa_exec["cobertura"].append({"planejado": "MED-PLANO-001", "status": "EXECUTADO", "executado": []})
    assert recalcular_execucao(plano, mentirosa_exec)["apto"] is False
    mentirosa_subst = copy.deepcopy(base)
    mentirosa_subst["cobertura"].append({
        "planejado": "MED-PLANO-001", "status": "SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE", "executado": [],
        "evidencia_equivalente": ["MED-EXEC-999"],
        "equivalencia": {"requisito_original": "MED-PLANO-001", "tipo_evidencia": "MEDICAO",
                         "capability": "abertura", "metodo_substituto": "paquimetro"},
        "justificativa_equivalencia": "z"})
    assert recalcular_execucao(plano, mentirosa_subst)["apto"] is False


def test_execucao_legacy_sem_requisitos_semanticos_nao_fabrica_apto():
    """P1 (PASS B contra 41dd08f): plano legado SEM a chave requisitos_semanticos
    era bloqueado no planning (cobertura semântica UNKNOWN) mas recalcular_execucao
    retornava apto=True — e nenhuma camada lia plano['status']. UNKNOWN nunca
    fabrica APTO: ausência da chave é falta explícita na execução (fail-closed)."""
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    plano = _plan_with([])
    del plano["requisitos_semanticos"]
    res = recalcular_execucao(plano, _vistoria_exec("ATV-001"))
    assert res["apto"] is False
    assert any("SEM_REQUISITOS_SEMANTICOS" in str(f.get("motivo", "")) for f in res["faltantes"])


def _cenario_longitudinal():
    """Caso sintético completo: delimitacao -> plano -> vistoria executada.
    Quesito 'Existe umidade na parede?' re-deriva INDETERMINADA -> exige medição."""
    import tempfile
    from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar
    from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
    from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
    from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
    from scripts.vistoria_estruturada.gerar_vistoria import gerar as gerar_vistoria
    from scripts.vistoria_estruturada.inventariar_vistoria import inventariar
    td = tempfile.TemporaryDirectory()
    d = Path(td.name)
    (d / "documentos").mkdir()
    manifesto = json.loads((ROOT / "tests/fixtures/pje/manifesto-minimo-valido.json").read_text(encoding="utf-8"))
    doc = json.loads((ROOT / "tests/fixtures/pje/documento-simples-valido.json").read_text(encoding="utf-8"))
    texto = ("A autora alega infiltracao, fissura, trinca e descolamento no imovel adquirido, decorrentes de vicio construtivo. "
             "O objeto da pericia e o imovel. O objetivo da pericia e determinar a causa.\n"
             "QUESITOS:\n1. Existe umidade na parede?\n2. Quem deve indenizar pelos danos?")
    doc["paginas"][0]["texto_bruto"] = texto
    doc["blocos_texto"] = [{"bloco_id": "BLT-001", "texto": texto, "pagina": doc["paginas"][0]["referencia"],
                            "proveniencia": doc["fontes"][0]}]
    (d / "manifesto-pje.json").write_text(json.dumps(manifesto), encoding="utf-8")
    (d / "documentos/DOC-PJE-001.json").write_text(json.dumps(doc), encoding="utf-8")
    doc2 = copy.deepcopy(doc)
    doc2["documento_id"] = "DOC-PJE-002"; doc2["id_pje"] = "900002"; doc2["classe_normalizada"] = "DECISAO"
    doc2["fontes"][0].update(documento_id="DOC-PJE-002", id_pje="900002")
    doc2["blocos_texto"][0]["proveniencia"].update(documento_id="DOC-PJE-002", id_pje="900002")
    (d / "documentos/DOC-PJE-002.json").write_text(json.dumps(doc2), encoding="utf-8")
    delimitacao = gerar_delimitacao(d)
    (d / "delimitacao-pericial.json").write_text(json.dumps(delimitacao), encoding="utf-8")
    processo = gerar_processo(d)
    (d / "processo.json").write_text(json.dumps(processo), encoding="utf-8")
    delimitacao = aprofundar(d)
    (d / "delimitacao-pericial.json").write_text(json.dumps(delimitacao), encoding="utf-8")
    plano = gerar_plano(d)
    campo = d / "campo"
    campo.mkdir()
    linhas = []
    for a in plano["atividades"]:
        linhas.append(f"tipo=OBS;registro_id={a['id']};descricao=condição examinada;manifestacao=umidade;"
                      f"resultado=OBSERVADO;sistema=IMPERMEABILIZACAO;atividade_planejada={a['id']}")
    for m in plano["medicoes"]:
        atv = next((a["id"] for a in plano["atividades"]
                    if set(a["questoes_tecnicas"]) & set(m["questoes_tecnicas"])), plano["atividades"][0]["id"])
        linhas.append(f"tipo=MED;vinculo_registro={atv};grandeza={m['grandeza']};valor=0,2;unidade=mm;medicao_planejada={m['id']}")
    (campo / "notas.txt").write_text("\n".join(linhas), encoding="utf-8")
    for i, f in enumerate(plano["fotografias"], 1):
        (campo / f"{f['id']}.jpg").write_bytes(f"imagem sintetica {i}".encode())
    vistoria = gerar_vistoria(inventariar(campo), plano, processo["numero_processo"])
    return td, processo, json.loads((d / "delimitacao-pericial.json").read_text(encoding="utf-8")), plano, vistoria


def test_longitudinal_semantico_bloqueio_e_liberacao_motor_redacao():
    """§7 CROSS-BOUNDARY: o bloqueio/liberação semântico propaga Planning ->
    Execution -> Motor -> Redação; nenhuma camada reconstrói COMPLETE de
    subconjunto relacional e UNKNOWN (legacy) nunca vira APTO downstream."""
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    from scripts.motor_vicios.pipeline import executar_pipeline_motor
    from scripts.redacao_pericial.pipeline import executar_pipeline_redacao

    # CASE 1 — happy path: requisito semântico + evidência executada apropriada.
    td, processo, delimitacao, plano, vistoria = _cenario_longitudinal()
    try:
        assert recalcular_execucao(plano, vistoria)["apto"] is True
        motor = executar_pipeline_motor(processo, delimitacao, plano, vistoria)
        assert motor["gate"] != "BLOQUEADO_PARA_REDACAO", motor.get("coverage_execucao")
        redacao = executar_pipeline_redacao(processo, delimitacao, motor)
        assert "laudo" in redacao
    finally:
        td.cleanup()

    # CASE 2 — medição planejada NÃO executada: bloqueio em todas as camadas.
    td, processo, delimitacao, plano, vistoria = _cenario_longitudinal()
    try:
        vistoria["medicoes"] = []
        for c in vistoria["cobertura"]:
            if c.get("tipo") == "MEDICAO":
                c["status"] = "PENDENTE"; c["executado"] = []
        assert recalcular_execucao(plano, vistoria)["apto"] is False
        motor = executar_pipeline_motor(processo, delimitacao, plano, vistoria)
        assert motor["gate"] == "BLOQUEADO_PARA_REDACAO"
        redacao = executar_pipeline_redacao(processo, delimitacao, motor)
        assert "laudo" not in redacao or redacao.get("gate") == "BLOQUEADO_PARA_LAUDO"
    finally:
        td.cleanup()

    # CASE 6 — legacy: plano sem a chave jamais adquire APTO downstream, mesmo
    # com a vistoria relacionalmente completa.
    td, processo, delimitacao, plano, vistoria = _cenario_longitudinal()
    try:
        legado = {k: v for k, v in plano.items() if k != "requisitos_semanticos"}
        assert recalcular_execucao(legado, vistoria)["apto"] is False
        motor = executar_pipeline_motor(processo, delimitacao, legado, vistoria)
        assert motor["gate"] == "BLOQUEADO_PARA_REDACAO"
        redacao = executar_pipeline_redacao(processo, delimitacao, motor)
        assert "laudo" not in redacao or redacao.get("gate") == "BLOQUEADO_PARA_LAUDO"
    finally:
        td.cleanup()


# ============================================================== V13 — autoridade
# AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1 (PASS A5+B5 contra 8438104, SAME_CLASS_
# SURVIVED pela 3ª vez consecutiva na MESMA classe causal): re-derivar a classe
# do texto a cada chamada fecha ADULTERAÇÃO, nunca AMBIGUIDADE — a saída de
# classificar_requisito ERA, ela mesma, a autoridade efetiva de cobertura.
# TEXT_CLASSIFIER_OUTPUT != EFFECTIVE_COVERAGE_AUTHORITY: classificar_requisito
# passa a ser só SUGESTÃO (suggested); evidencia_requerida é a AUTORIDADE
# (required) — nunca confiada de forma persistida (igual a `classe`, sempre
# re-derivada), e estritamente mais conservadora quando a sugestão dependeu de
# confiar num marcador para absolver um objeto desconhecido (TIER 2).


def test_pp_locativo_nao_absolve_de_complemento_embutido_no_proprio_span_v13():
    """P0 (PASS A5+B5 contra 8438104, SAME_CLASS_SURVIVED — 3ª rodada): o PP
    locativo bounded (até 3 palavras) ainda descartava incondicionalmente um
    de-complemento embutido no seu PRÓPRIO span ('na parede DO ZETA' inteiro
    virava 'local', sem nunca alcançar a contabilidade de resíduo) — mesma
    classe causal, terceiro vetor dentro do próprio mecanismo de reparo. O PP
    locativo não consome mais nenhuma continuação 'de X': remove só a
    preposição + o substantivo do local; qualquer 'de X' que viesse a seguir
    fica adjacente ao head do fenômeno e passa pelo MESMO mecanismo de
    complemento (_COMPLEMENTO_SEGURO/_MARCADOR_VISUAL) usado em todo o resto."""
    for texto in [
        "Verificar a fissura na parede do zeta.",
        "Constatar a mancha no teto do dormitorio.",
        "Constatar o mofo na parede do closet.",
        "Avaliar a mancha na parede do lambda.",
        "Verificar a trinca junto a parede do omega.",
        "Verificar a fissura na parede do zeta e a trinca no muro do lambda.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_sugestao_inspecao_via_tier2_nao_promove_autoridade_observacional_v13():
    """RED A/E do LOOP BREAKER: classificar_requisito (sugestão) pode dizer
    INSPECAO com base em prova de modo (marcador visual) absolvendo um
    complemento desconhecido — mas essa promoção sozinha NUNCA vira autoridade
    efetiva. 'suggested_evidence_kind=OBSERVATIONAL' sem uma re-verificação
    ESTRITA (só vocabulário fechado, sem depender de marcador) não cobre."""
    for texto in [
        "Fotografar a fissura de lambda na viga.",
        "Registrar a mancha de zeta visível na parede.",
        "Fotografar a mancha do zeta.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto  # sugestão preservada
        assert evidencia_requerida(texto) == "DESCONHECIDA", texto  # autoridade não promove
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto


def test_evidencia_requerida_estrita_promove_quando_tudo_e_vocabulario_fechado_v13():
    """RED G do LOOP BREAKER: quando a demanda inteira resolve em modo ESTRITO
    (nenhuma palavra desconhecida absolvida por marcador — só cabeça
    reconhecida, complemento seguro ou qualificador), a autoridade PROMOVE a
    OBSERVACIONAL e a cobertura por atividade apropriada funciona normalmente
    — a separação suggested/required não inutiliza o caminho observacional
    legítimo, só recusa promovê-lo sob ambiguidade real."""
    for texto in [
        "Verificar a fissura da parede.",
        "Constatar a existência de infiltração aparente.",
        "Verificar se há goteira visível no forro.",
        "Caracterizar as manifestações patológicas alegadas.",
        "Apontar as manchas de umidade na laje.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto
        assert evidencia_requerida(texto) == "OBSERVACIONAL", texto
    r = recalcular_cobertura(_plan_with([_r("R1", "Verificar a fissura da parede.", ["ATV-001"])]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is True
    assert r["apto"] is True


def test_evidencia_requerida_persistida_mentirosa_e_ignorada_v13():
    """RED D/E do LOOP BREAKER: `evidencia_requerida` persistida em
    requisitos_semanticos[] (informativa, escrita pelo gerador) NUNCA é
    autoridade — igual a `classe`, sempre re-derivada do texto. Persistir
    'OBSERVACIONAL' à força sobre um requisito cuja re-derivação estrita dá
    DESCONHECIDA não fabrica cobertura."""
    texto = "Fotografar a fissura de lambda na viga."
    entrada = _r("R1", texto, ["ATV-001"])
    entrada["evidencia_requerida"] = "OBSERVACIONAL"
    entrada["classe"] = "INSPECAO"
    r = recalcular_cobertura(_plan_with([entrada]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["apto"] is False


def test_evidencia_requerida_ausente_em_legado_e_desconhecida_v13():
    """RED C do LOOP BREAKER: campo `evidencia_requerida` ausente (plano
    legado gerado antes do V13) nunca fabrica valor efetivo — a autoridade é
    sempre re-derivada do texto do requisito, nunca lida do campo ausente, e
    o resultado (DESCONHECIDA para uma demanda cuja re-derivação estrita não
    resolve) é idêntico a uma execução que nunca teve o campo."""
    texto = "Fotografar a fissura de lambda na viga."
    entrada = _r("R1", texto, ["ATV-001"])
    assert "evidencia_requerida" not in entrada
    r = recalcular_cobertura(_plan_with([entrada]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["apto"] is False


def test_evidencia_metrologica_com_atividade_generica_nao_cobre_v13():
    """RED F do LOOP BREAKER: required_evidence_kind=METROLOGICA (via
    evidencia_requerida) nunca é satisfeito por uma atividade genérica — só
    por medição/ensaio, exatamente como MEDICAO já exigia antes do V13."""
    r = recalcular_cobertura(_plan_with([_r("R1", "Medir a estanqueidade da laje sob pressão.", ["ATV-001"])]))
    assert evidencia_requerida("Medir a estanqueidade da laje sob pressão.") == "METROLOGICA"
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["apto"] is False


def test_pp_locativo_exige_vocabulario_fechado_v131():
    """P0 (PASS A6 contra ed3e7ee, SAME_CLASS_SURVIVED — 4ª rodada, mesmo com
    a separação sugestão/autoridade já confirmada genuína): o PP locativo
    limitado a uma palavra (V12.2) ainda a deletava incondicionalmente, sem
    NENHUMA verificação de conteúdo — 'na parede DO ZETA' virava 'local'
    mesmo sem 'do zeta', e um local desconhecido isolado ('no ZETA') era
    descartado por inteiro antes de alcançar a contabilidade de resíduo. A
    deleção acontecia ANTES do split TIER1/TIER2, então nem o modo estrito de
    evidencia_requerida via o conteúdo. O PP locativo agora só remove a
    preposição quando a palavra seguinte pertence ao MESMO vocabulário
    fechado do de-complemento (_COMPLEMENTO_SEGURO)."""
    for texto in [
        "Verificar a fissura no zeta.",
        "Constatar a mancha no teto do dormitorio.",
        "Verificar a fissura na parede do zeta.",
        "Verificar a trinca junto a parede do omega.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["apto"] is False, texto
    # contraparte positiva: local conhecido continua removido normalmente.
    assert evidencia_requerida("Verificar a mancha na estrutura.") == "OBSERVACIONAL"


def test_vocabulario_fechado_nao_absorve_sufixo_colado_v131():
    """P0 (PASS A6 contra ed3e7ee, SAME_CLASS_SURVIVED): todo vocabulário
    fechado desta contabilidade (_FENOMENO_OBSERVAVEL, _OBJETO_DESCRITIVO,
    _COMPLEMENTO_SEGURO) terminava em `\\w*` — irrestrito, não apenas flexão.
    'parede'+'\\w*' também casava 'paredeZETA' por inteiro, um artefato
    plausível de extração de PDF/OCR que perde o espaço entre duas palavras
    reais. Sufixos agora são fechados (_FLEX ou alternativa explícita): só
    flexão PT-BR real é absorvida, qualquer sufixo colado sobra como resíduo."""
    for texto in [
        "Verificar a fissura do paredezeta.",          # complemento colado
        "Verificar a fissura da paredezeta.",
        "Verificar a fissurazeta.",                     # head (fenômeno) colado
        "Verificar a manchazeta.",
        "Descrever o padrao construtivozeta do imovel.",  # head (descritivo) colado
        "Descrever o padrao construtivo do imovelzeta.",  # complemento seguro colado
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto
    # contrapartes positivas: flexão real continua reconhecida normalmente.
    for texto in [
        "Verificar a fissura da parede.", "Verificar as fissuras das paredes.",
        "Descrever o padrao construtivo do imovel.",
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto
        assert evidencia_requerida(texto) == "OBSERVACIONAL", texto


def test_residuo_de_token_curto_nao_escapa_da_contabilidade_v131():
    """P0 (achado incidental durante a verificação em escala do PASS A6): um
    token de 1-2 letras nunca contava como resíduo (\\w{3,}) — uma
    sigla/abreviação técnica curta e nunca vista escapava da contabilidade
    mesmo sem vocabulário nem marcador algum. Limite reduzido para \\w{2,}."""
    for texto in [
        "Verificar a fissura no wz.",
        "Verificar a mancha na ph.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto


def test_primitivas_irmas_da_contabilidade_tambem_tem_sufixo_fechado_v132():
    """P0 (PASS A7+B7 contra a5626b7, SAME_CLASS_SURVIVED — 5ª rodada): o V13.1
    fechou o `\\w*` só em _FENOMENO_OBSERVAVEL/_OBJETO_DESCRITIVO/
    _COMPLEMENTO_SEGURO; o MESMO bug sobreviveu em TODA outra primitiva que a
    `_contabilidade_observacional` remove ou consome antes da checagem de
    resíduo — _SCAFFOLD (presenc/ausenc/alegad/existenc), _MARCADOR_VISUAL
    (fotograf), _QUALIFICADOR_NP (fotograf/localizad/generalizad/alegad) e o
    verbo-líder _VERBO_TECNICO (analis). Um token desconhecido colado a
    qualquer um desses radicais era apagado como se fosse flexão e nunca
    virava resíduo. Sufixos agora FECHADOS em todas."""
    for texto in [
        "Verificar a presencazeta de fissura.",          # _SCAFFOLD
        "Descrever a mancha ausenciazeta.",
        "Verificar a fissura alegadazeta.",
        "Verificar a fissura fotografiazeta.",            # _MARCADOR_VISUAL
        "Verificar a fissura localizadazeta.",            # _QUALIFICADOR_NP
        "Verificar a fissura generalizadaomega na parede.",
        "Caracterizar as manifestacoes alegadaszeta.",
        "Analisezeta a fissura.",                         # _VERBO_TECNICO (analis)
        "Analisekappa a mancha na parede.",
    ]:
        assert classificar_requisito(texto) != "INSPECAO", texto
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["apto"] is False, texto
    # contrapartes positivas: formas legítimas dessas primitivas continuam.
    for texto in [
        "Constatar a presenca de mofo no banheiro.",
        "Constatar a ausencia de fissuras aparentes.",
        "Verificar a fissura alegada na viga.",
        "Registrar fotograficamente o estado geral do imovel.",
        "Registrar a fissura localizada na parede.",
        "Analisar a fissura da parede.",
        "Descrever a bolha na pintura.",                  # P2 regressão V13.1 corrigida
    ]:
        assert classificar_requisito(texto) == "INSPECAO", texto
        assert evidencia_requerida(texto) == "OBSERVACIONAL", texto


def test_flex_so_admite_s_nao_es_para_radical_terminado_em_vogal_v132():
    """P2 (PASS A7): `_FLEX = (?:s|es)?` aceitava 'paredees' (radical + 'es');
    todo radical que usa _FLEX termina em vogal (plural regular só '+s'). _FLEX
    reduzido para 's?'; os poucos radicais consoante-final têm '(?:es)?'
    explícito."""
    assert evidencia_requerida("Verificar a fissura da paredees.") != "OBSERVACIONAL"
    assert evidencia_requerida("Verificar as fissuras das paredes.") == "OBSERVACIONAL"
    assert evidencia_requerida("Verificar as trincas dos pilares.") == "OBSERVACIONAL"  # (?:es)? explícito


def test_autoridade_loss_aware_normalizacao_e_residuo_de_1_char_v133():
    """P0 (PASS B8 contra 527af78, SAME_CLASS_SURVIVED — 6ª rodada): duas
    perdas estruturais faziam a autoridade ler "não vejo resíduo" como
    "provei que não há resíduo": (A) normalizar() (NFKD + ascii-ignore)
    apagava um símbolo técnico não-ASCII (σ/λ/φ/θ/µ/Ø) ANTES da contabilidade;
    (B) o filtro de resíduo `\\w{2,}` era cego a um token desconhecido de 1
    caractere ('x'/'5') e a um fragmentado por pontuação ('a-b'→'a','b').
    `evidencia_requerida` agora exige, além da prova estrita, que NENHUM
    conteúdo material tenha sido apagado (_perda_na_normalizacao, por
    CATEGORIA Unicode — não hardcode dos símbolos) e usa piso de resíduo em
    cardinalidade ≥1 no modo estrito. `ABSENCE_AFTER_LOSSY_NORMALIZATION !=
    PROOF_OF_SEMANTIC_COMPLETENESS`; SILENT LOSS MUST NEVER BECOME CERTAINTY."""
    reds = [
        "Verificar a fissura do σ.",           # sigma (tensão)
        "Verificar a fissura do λ.",           # lambda (esbeltez)
        "Descrever a mancha do θ na parede.",   # theta (ângulo)
        "Verificar a infiltracao do µ.",        # micro (atrito)
        "Verificar a fissura do Ø.",            # Ø (diâmetro)
        "Verificar a fissura do x.",                 # 1 letra ASCII
        "Verificar a fissura do 5.",                 # 1 dígito
        "Verificar a fissura do a-b.",               # fragmentado por hífen
        "Verificar a fissura do x/y.",               # fragmentado por barra
        "Verificar a fissura do p.q.",               # fragmentado por ponto
    ]
    for texto in reds:
        assert evidencia_requerida(texto) != "OBSERVACIONAL", texto
        r = recalcular_cobertura(_plan_with([_r("R1", texto, ["ATV-001"])]))
        assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False, texto
        assert r["apto"] is False, texto
    # controles positivos — diacrítico normal do português NÃO é perda.
    for texto in [
        "Verificar a fissura da parede.",
        "Constatar a presenca de mofo no banheiro.",
        "Descrever a bolha na pintura.",
        "Caracterizar as manifestacoes patologicas alegadas.",
        "Registrar fotograficamente o estado geral do imovel.",
    ]:
        assert evidencia_requerida(texto) == "OBSERVACIONAL", texto


def test_metamorfico_conhecido_mais_desconhecido_nunca_mais_permissivo_v133():
    """Propriedade metamórfica (§11 do loss-aware repair): um requisito
    observacional CONHECIDO, ao ganhar CONTEÚDO DESCONHECIDO (em qualquer
    codificação — ASCII, símbolo Unicode, dígito, hifenizado, barra, ponto,
    ruído tipo OCR), NUNCA pode ficar MAIS permissivo — só igual (se o
    desconhecido for absorvido como vocabulário fechado, o que não deve
    acontecer) ou mais estrito (DESCONHECIDA)."""
    base = "Verificar a fissura da parede"
    assert evidencia_requerida(base + ".") == "OBSERVACIONAL"
    desconhecidos = [
        "zeta", "xpto", "brixon",                    # ASCII multi-char
        "σ", "λ", "φ", "∑",       # símbolos Unicode
        "5", "12", "x9",                              # dígitos
        "a-b", "p-q",                                 # hífen
        "x/y", "a/b",                                 # barra
        "p.q", "x.9",                                 # ponto
        "l1", "rn",                                   # ruído tipo OCR
    ]
    for tk in desconhecidos:
        for conn in ("do", "da", "no", "com"):
            texto = f"{base} {conn} {tk}."
            assert evidencia_requerida(texto) != "OBSERVACIONAL", texto


def test_perda_na_normalizacao_ignora_diacritico_do_portugues_v133():
    """`_perda_na_normalizacao` distingue perda MATERIAL (letra/símbolo
    não-ASCII apagado) de mera decomposição de acento — á/ç/ã/õ/â/ê/ô/ü NUNCA
    são perda; σ/λ/µ/Ø/× são."""
    from scripts.planejamento_pericial.requisitos_materiais import _perda_na_normalizacao
    for texto in ["edificação", "área construída", "manutenção do imóvel",
                  "pé-direito", "avaliação técnica", "distribuição dos cômodos"]:
        assert _perda_na_normalizacao(texto) is False, texto
    for texto in ["tensão σ", "esbeltez λ", "coef. µ",
                  "diâmetro Ø", "3 × 4"]:
        assert _perda_na_normalizacao(texto) is True, texto


def test_evidencia_requerida_recheck_motor_preserva_autoridade_v13():
    """A autoridade (evidencia_requerida) é a MESMA em Planning e no recheck do
    motor de vícios — nenhuma camada re-classifica com um critério próprio."""
    from scripts.motor_vicios.pipeline import _plano_para_recheck
    texto = "Fotografar a fissura de lambda na viga."
    plano = _plan_with([_r("R1", texto, ["ATV-001"])])
    recheck = _plano_para_recheck(plano)
    assert recalcular_cobertura(recheck)["apto"] is False
    assert recalcular_cobertura(plano)["apto"] is False

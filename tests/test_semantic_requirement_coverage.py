"""#182 — cobertura de requisito material é decidida por vínculo estruturado
explícito, nunca por semelhança textual nem por auto-injeção de texto.

Relacional responde "o quesito está ligado ao plano?".
Semântica responde "todos os requisitos materiais do quesito têm destino verificável?".
apto exige as duas em 100% e zero requisitos não mapeados.
"""

import copy
import json
from pathlib import Path

from scripts.planejamento_pericial.validar_plano import recalcular_cobertura
from scripts.planejamento_pericial.requisitos_materiais import (
    extrair_requisitos_materiais,
    remover_ruido_estrutural,
)

ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return json.loads(
        (ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8")
    )


def _atv(id_, verificar):
    return {
        "id": id_, "verificar": verificar, "justificativa": "j", "questoes_tecnicas": ["QT-001"],
        "quesitos": ["QUE-001"], "alegacoes": [], "metodo": "Inspeção", "fundamentos": [],
        "evidencia_esperada": "registro", "obrigatoriedade": "OBRIGATORIA",
        "consequencia_se_nao_realizada": "limitação",
    }


def _plan_with(reqs, atividades):
    plan = _plan()
    plan["atividades"] = atividades
    plan["cobertura"][0]["atividades"] = [a["id"] for a in atividades]
    plan["requisitos_cobertura"] = [
        {"questao_tecnica": "QT-001", "tipo": "ATIVIDADE", "obrigatoriedade": "OBRIGATORIA", "item_planejado": a["id"]}
        for a in atividades
    ]
    plan["requisitos_semanticos"] = reqs
    return plan


# ---------------------------------------------------------------- gate: matriz


def test_A_um_requisito_um_destino_correto():
    plan = _plan_with(
        [{"requirement_id": "REQ-001-A", "quesito": "QUE-001", "requisito": "Verificar a fissura da parede.", "itens_planejados": ["ATV-001"]}],
        [_atv("ATV-001", "Verificar a fissura da parede.")],
    )
    r = recalcular_cobertura(plan)
    assert r["cobertura_relacional"]["QUE-001"] is True
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is True
    assert (r["requisitos_materiais_cobertos"], r["total_requisitos_materiais"]) == (1, 1)
    assert r["requisitos_materiais_nao_mapeados"] == []
    assert r["cobertura_semantica_fracao"] == 1.0
    assert r["apto"] is True


def test_B_quatro_requisitos_destino_cobre_tres():
    atv = _atv("ATV-001", "Medir a fissura, a umidade e o recalque da parede.")
    reqs = [
        {"requirement_id": f"REQ-001-{i}", "quesito": "QUE-001", "requisito": t, "itens_planejados": ["ATV-001"]}
        for i, t in enumerate(["Medir a fissura da parede.", "Medir a umidade da parede.", "Medir o recalque da parede.", "Ensaiar a resistência do concreto estrutural."])
    ]
    r = recalcular_cobertura(_plan_with(reqs, [atv]))
    assert r["cobertura_relacional"]["QUE-001"] is True
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert (r["requisitos_materiais_cobertos"], r["total_requisitos_materiais"]) == (3, 4)
    assert len(r["requisitos_materiais_nao_mapeados"]) == 1
    assert r["cobertura_semantica_fracao"] == 0.75
    assert r["apto"] is False


def test_C_atividade_generica_nao_conta_para_todos():
    generica = _atv("ATV-001", "Inspecionar de forma geral o imóvel.")
    reqs = [
        {"requirement_id": "REQ-001-1", "quesito": "QUE-001", "requisito": "Inspecionar de forma geral o imóvel.", "itens_planejados": ["ATV-001"]},
        {"requirement_id": "REQ-001-2", "quesito": "QUE-001", "requisito": "Medir a estanqueidade da laje sob pressão.", "itens_planejados": ["ATV-001"]},
    ]
    r = recalcular_cobertura(_plan_with(reqs, [generica]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["requisitos_materiais_cobertos"] == 1
    assert r["apto"] is False


def test_D_requisito_sem_destino_e_estado_legitimo():
    plan = _plan_with(
        [{"requirement_id": "REQ-001-1", "quesito": "QUE-001", "requisito": "Ensaiar a resistência do concreto.", "itens_planejados": [], "status": "NAO_MAPEADO"}],
        [_atv("ATV-001", "Verificar a fissura.")],
    )
    r = recalcular_cobertura(plan)
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert r["requisitos_materiais_nao_mapeados"] == ["REQ-001-1"]
    assert r["apto"] is False


def test_J_limitacao_explicita_e_rastreavel_nao_silenciosa():
    plan = _plan_with(
        [{"requirement_id": "REQ-001-1", "quesito": "QUE-001", "requisito": "Abrir prova destrutiva na estrutura.", "itens_planejados": [], "status": "EXTRACAO_INDETERMINADA"}],
        [_atv("ATV-001", "Verificar a fissura.")],
    )
    r = recalcular_cobertura(plan)
    assert "REQ-001-1" in r["requisitos_materiais_nao_mapeados"]
    assert r["apto"] is False


def test_K_quesito_nao_pertinente_fora_do_denominador():
    plan = _plan_with(
        [{"requirement_id": "REQ-001-1", "quesito": "QUE-001", "requisito": "Verificar a fissura.", "itens_planejados": ["ATV-001"]},
         {"requirement_id": "REQ-999-1", "quesito": "QUE-999", "requisito": "materia estranha", "itens_planejados": []}],
        [_atv("ATV-001", "Verificar a fissura.")],
    )
    r = recalcular_cobertura(plan)
    assert r["total_requisitos_materiais"] == 1
    assert r["apto"] is True


def test_L_status_bloqueado_permanece_com_requisito_nao_mapeado():
    plan = _plan_with(
        [{"requirement_id": "REQ-001-1", "quesito": "QUE-001", "requisito": "Ensaiar concreto.", "itens_planejados": []}],
        [_atv("ATV-001", "Verificar a fissura.")],
    )
    plan["status"] = "BLOQUEADO_PARA_VISTORIA"
    r = recalcular_cobertura(plan)
    assert r["apto"] is False and r["requisitos_materiais_nao_mapeados"]


# ------------------------------------------------------------- mutation kills


def test_M1_apto_nao_ignora_cobertura_semantica():
    r = recalcular_cobertura(_plan_with(
        [{"requirement_id": "R1", "quesito": "QUE-001", "requisito": "Ensaiar concreto.", "itens_planejados": []}],
        [_atv("ATV-001", "Verificar a fissura.")]))
    assert r["cobertura_relacional"]["QUE-001"] is True and r["apto"] is False


def test_M2_requisito_nao_mapeado_nao_e_descartado():
    r = recalcular_cobertura(_plan_with(
        [{"requirement_id": "R1", "quesito": "QUE-001", "requisito": "Verificar a fissura.", "itens_planejados": ["ATV-001"]},
         {"requirement_id": "R2", "quesito": "QUE-001", "requisito": "Ensaiar concreto.", "itens_planejados": []}],
        [_atv("ATV-001", "Verificar a fissura.")]))
    assert r["total_requisitos_materiais"] == 2 and r["requisitos_materiais_nao_mapeados"] == ["R2"]


def test_M3_atividade_generica_com_todos_os_ids_nao_cobre_tudo():
    reqs = [
        {"requirement_id": f"R{i}", "quesito": "QUE-001", "requisito": t, "itens_planejados": ["ATV-001"]}
        for i, t in enumerate(["Verificar a fissura.", "Medir a umidade higroscópica.", "Ensaiar a aderência cerâmica.", "Calcular o recalque diferencial."])
    ]
    r = recalcular_cobertura(_plan_with(reqs, [_atv("ATV-001", "Verificar a fissura.")]))
    assert r["requisitos_materiais_cobertos"] == 1 and r["apto"] is False


def test_M4_extracao_vazia_nao_vira_cem_por_cento():
    q = {"id": "QUE-001", "pertinencia": "PERTINENTE_TECNICO", "texto_integral": "Num. 900001 - Pag. 1\nPagina complementar sem rodape", "materia_tecnica": "Num. 900001 - Pag. 1", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert len(reqs) == 1 and reqs[0]["status"] == "EXTRACAO_INDETERMINADA"
    r = recalcular_cobertura(_plan_with(
        [{**reqs[0]}], [_atv("ATV-001", "Verificar a fissura.")]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


# --------------------------------------------------------- false-green oracle


def test_false_green_text_injection_nao_converte_em_coberto():
    """Mesmo que o texto do requisito apareça na atividade, sem vínculo
    estruturado (itens_planejados) não há cobertura: a autoridade é o
    mapeamento, não a presença textual posterior."""
    atv = _atv("ATV-001", "Inspecionar telhado. Requisito do quesito: Ensaiar a resistência do concreto estrutural.")
    r = recalcular_cobertura(_plan_with(
        [{"requirement_id": "R1", "quesito": "QUE-001", "requisito": "Ensaiar a resistência do concreto estrutural.", "itens_planejados": []}],
        [atv]))
    assert r["cobertura_requisitos_semanticos"]["QUE-001"] is False and r["apto"] is False


def test_generator_never_fabricates_semantic_coverage_by_text_injection():
    fonte = (ROOT / "scripts/planejamento_pericial/gerar_plano.py").read_text(encoding="utf-8")
    assert 'verificar"] +=' not in fonte
    assert "Requisito do quesito:" not in fonte


def test_gate_nao_usa_similaridade_fuzzy_como_autoridade():
    fonte = (ROOT / "scripts/planejamento_pericial/validar_plano.py").read_text(encoding="utf-8")
    for proibido in ("cosine", "embedding", "SequenceMatcher", "difflib", "similarity_score"):
        assert proibido not in fonte


# ------------------------------------------------------------ extraction: matriz


def test_H_ruido_estrutural_nao_vira_requisito():
    assert remover_ruido_estrutural("Existe umidade na parede? Num. 900001 - Pag. 1\nPagina complementar sem rodape") == "Existe umidade na parede?"
    q = {"id": "QUE-001", "texto_integral": "Verificar a fissura da parede. Num. 900123 - Pag. 4", "materia_tecnica": None, "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert all("900123" not in r["requisito"] and "Pag." not in r["requisito"] for r in reqs)
    assert any("fissura" in r["texto_normalizado"] for r in reqs)


def test_I_multiplas_clausulas_geram_multiplos_requisitos():
    q = {"id": "QUE-002", "materia_tecnica": "Verificar a existência de fissuras; avaliar a extensão do dano e estimar o custo do reparo.", "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-002"]}
    reqs = [r for r in extrair_requisitos_materiais(q) if r["status"] == "MATERIAL"]
    assert len(reqs) >= 3
    assert len({r["requirement_id"] for r in reqs}) == len(reqs)


def test_E_requisitos_distintos_com_palavras_sobrepostas_nao_colapsam():
    q = {"id": "QUE-001", "materia_tecnica": "Caracterizar o acabamento superficial da laje. Documentar a geometria da laje.", "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [r for r in extrair_requisitos_materiais(q) if r["status"] == "MATERIAL"]
    assert len(reqs) == 2
    assert reqs[0]["requirement_id"] != reqs[1]["requirement_id"]


def test_F_clausula_identica_repetida_e_deduplicada_deterministicamente():
    q = {"id": "QUE-001", "materia_tecnica": "Medir a fissura da parede. Medir a fissura da parede.", "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = [r for r in extrair_requisitos_materiais(q) if r["status"] == "MATERIAL"]
    assert len(reqs) == 1


def test_G_reordenar_clausulas_preserva_identidade_dos_requisitos():
    base = "Medir a fissura da parede. Avaliar a umidade do piso."
    inv = "Avaliar a umidade do piso. Medir a fissura da parede."
    a = {r["texto_normalizado"]: r["requirement_id"] for r in extrair_requisitos_materiais({"id": "QUE-001", "materia_tecnica": base, "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": []})}
    b = {r["texto_normalizado"]: r["requirement_id"] for r in extrair_requisitos_materiais({"id": "QUE-001", "materia_tecnica": inv, "texto_integral": "x", "subitens": [], "questoes_tecnicas_relacionadas": []})}
    assert a == b and len(a) == 2


def test_zero_material_requirements_falha_fechado():
    q = {"id": "QUE-001", "pertinencia": "PERTINENTE_TECNICO", "materia_tecnica": "   \n  ", "texto_integral": "  ", "subitens": [], "questoes_tecnicas_relacionadas": ["QT-001"]}
    reqs = extrair_requisitos_materiais(q)
    assert len(reqs) == 1 and reqs[0]["status"] == "EXTRACAO_INDETERMINADA"


# ---------------------------------------------------- os 4 REDs originais (V3)


def test_relational_links_do_not_claim_semantic_requirement_coverage():
    plan = _plan()
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Verificar a estanqueidade da junta sintética.", "itens_planejados": []}
    ]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_each_semantic_requirement_needs_a_matching_planned_item():
    plan = _plan()
    plan["atividades"].append({**copy.deepcopy(plan["atividades"][0]), "id": "ATV-002", "verificar": "Verificar a estanqueidade da junta sintética."})
    plan["cobertura"][0]["atividades"].append("ATV-002")
    plan["requisitos_cobertura"].append({"questao_tecnica": "QT-001", "tipo": "ATIVIDADE", "obrigatoriedade": "OBRIGATORIA", "item_planejado": "ATV-002"})
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Verificar a estanqueidade da junta sintética.", "itens_planejados": ["ATV-002"]},
        {"quesito": "QUE-001", "requisito": "Conferir o isolamento acústico do painel sintético.", "itens_planejados": []},
    ]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_topic_overlap_does_not_substitute_the_exact_requirement():
    plan = _plan()
    plan["atividades"][0]["verificar"] = "Inspecionar superficialmente a junta sintética."
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Medir a estanqueidade da junta sintética sob pressão controlada.", "itens_planejados": ["ATV-001"]}
    ]
    result = recalcular_cobertura(plan)
    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_semantic_coverage_is_order_invariant():
    plan = _plan()
    plan["atividades"][0]["verificar"] = (
        "Caracterizar o acabamento superficial sintético e documentar a geometria do elemento sintético."
    )
    plan["requisitos_semanticos"] = [
        {"quesito": "QUE-001", "requisito": "Caracterizar o acabamento superficial sintético.", "itens_planejados": ["ATV-001"]},
        {"quesito": "QUE-001", "requisito": "Documentar a geometria do elemento sintético.", "itens_planejados": ["ATV-001"]},
    ]
    first = recalcular_cobertura(plan)
    plan["requisitos_semanticos"].reverse()
    second = recalcular_cobertura(plan)
    assert first == second
    assert first["cobertura_requisitos_semanticos"]["QUE-001"] is True
    assert first["apto"] is True

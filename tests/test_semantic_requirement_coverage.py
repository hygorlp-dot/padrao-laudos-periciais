import copy
import json
from pathlib import Path

from scripts.planejamento_pericial.validar_plano import recalcular_cobertura


ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return json.loads(
        (ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(
            encoding="utf-8"
        )
    )


def test_relational_links_do_not_claim_semantic_requirement_coverage():
    plan = _plan()
    plan["requisitos_semanticos"] = [
        {
            "quesito": "QUE-001",
            "requisito": "Verificar a estanqueidade da junta sintética.",
            "itens_planejados": [],
        }
    ]

    result = recalcular_cobertura(plan)

    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_each_semantic_requirement_needs_a_matching_planned_item():
    plan = _plan()
    plan["atividades"].append(
        {
            **copy.deepcopy(plan["atividades"][0]),
            "id": "ATV-002",
            "verificar": "Verificar a estanqueidade da junta sintética.",
        }
    )
    plan["cobertura"][0]["atividades"].append("ATV-002")
    plan["requisitos_semanticos"] = [
        {
            "quesito": "QUE-001",
            "requisito": "Verificar a estanqueidade da junta sintética.",
            "itens_planejados": ["ATV-002"],
        },
        {
            "quesito": "QUE-001",
            "requisito": "Conferir o isolamento acústico do painel sintético.",
            "itens_planejados": [],
        },
    ]

    result = recalcular_cobertura(plan)

    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_topic_overlap_does_not_substitute_the_exact_requirement():
    plan = _plan()
    plan["atividades"][0]["verificar"] = "Inspecionar superficialmente a junta sintética."
    plan["requisitos_semanticos"] = [
        {
            "quesito": "QUE-001",
            "requisito": "Medir a estanqueidade da junta sintética sob pressão controlada.",
            "itens_planejados": ["ATV-001"],
        }
    ]

    result = recalcular_cobertura(plan)

    assert result["cobertura_relacional"]["QUE-001"] is True
    assert result["cobertura_requisitos_semanticos"]["QUE-001"] is False
    assert result["apto"] is False


def test_semantic_coverage_is_order_invariant():
    plan = _plan()
    plan["atividades"][0]["verificar"] = (
        "Caracterizar o acabamento superficial sintético e documentar a geometria "
        "do elemento sintético."
    )
    plan["requisitos_semanticos"] = [
        {
            "quesito": "QUE-001",
            "requisito": "Caracterizar o acabamento superficial sintético.",
            "itens_planejados": ["ATV-001"],
        },
        {
            "quesito": "QUE-001",
            "requisito": "Documentar a geometria do elemento sintético.",
            "itens_planejados": ["ATV-001"],
        },
    ]

    first = recalcular_cobertura(plan)
    plan["requisitos_semanticos"].reverse()
    second = recalcular_cobertura(plan)

    assert first == second
    assert first["cobertura_requisitos_semanticos"]["QUE-001"] is True
    assert first["apto"] is True

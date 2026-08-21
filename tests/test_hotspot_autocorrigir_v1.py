"""Characterization contracts for HOTSPOT-05 (motor autocorrection)."""

import copy
import json
from pathlib import Path

from scripts.motor_vicios.autocorrigir import autocorrigir


CORPUS = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_corpus" / "autocorrigir.json").read_text(encoding="utf-8")
)
BASE_INPUT = CORPUS["cases"][0]["input"]


def _entrada_base():
    return copy.deepcopy(BASE_INPUT)


def test_claim_de_origem_reprovada_preserva_reducao_e_historico_exatos():
    entrada = _entrada_base()
    entrada["claims"][0]["tipo"] = "ORIGEM"
    resultado_antes = copy.deepcopy(entrada["resultado"])

    final, historico = autocorrigir(**entrada)

    patologia = final["patologias"][0]
    assert patologia["origem"] == "INCONCLUSIVA"
    assert patologia["vicio_construtivo"] == {
        "caracterizado": False,
        "tipo": "INCONCLUSIVO",
        "fundamentacao": None,
    }
    assert patologia["elegibilidade_orcamento"] == "PENDENTE"
    assert historico[0] == {
        "id": "AUT-001",
        "alvo": "CLM-001",
        "claim": "CLM-001",
        "valor_antes": "ENDOGENA_CONSTRUTIVA",
        "veredito": "UNSUBSTANTIATED",
        "evidencia": "OBS-001",
        "acao": "REDUZIR_ORIGEM",
        "valor_depois": "INCONCLUSIVA",
        "motivo": "Origem dependia de claim não sustentada.",
        "achado_originador": "CLM-001",
    }
    assert entrada["resultado"] == resultado_antes


def test_autoridade_autodeclarada_reduz_evidencia_e_norma_relacionada():
    entrada = _entrada_base()
    entrada["claims"] = []
    entrada["auditorias"] = []
    entrada["resultado"]["catalogo_evidencias"] = [
        {"id": "EVD-001", "authority": "FONTE_OFICIAL_VERIFICADA"}
    ]
    entrada["resultado"]["patologias"][0]["normas_relacionadas"] = [
        {
            "id": "NOR-001",
            "authority": "FONTE_PRIMARIA_OFICIAL",
            "classificacao_fonte": "FONTE_SECUNDARIA",
        }
    ]
    entrada["achados"] = [
        {"tipo": "AUTORIDADE_NORMATIVA_AUTODECLARADA", "claim_id": "EVD-001"}
    ]
    resultado_antes = copy.deepcopy(entrada["resultado"])

    final, historico = autocorrigir(**entrada)

    assert final["catalogo_evidencias"][0]["authority"] == "NAO_DETERMINADA"
    assert final["patologias"][0]["normas_relacionadas"][0]["authority"] == "NAO_DETERMINADA"
    assert [item["acao"] for item in historico] == [
        "REMOVER_AUTORIDADE_AUTODECLARADA",
        "APLICAR_CORRECAO_DETECTOR",
        "FINALIZAR_ESTADO_CORRIGIDO",
    ]
    assert entrada["resultado"] == resultado_antes


def test_tipo_de_claim_desconhecido_nao_inventa_reducao():
    entrada = _entrada_base()
    entrada["claims"][0]["tipo"] = "TIPO_DESCONHECIDO"

    final, historico = autocorrigir(**entrada)

    assert final["patologias"][0]["origem"] == "ENDOGENA_CONSTRUTIVA"
    assert [item["acao"] for item in historico] == ["FINALIZAR_ESTADO_CORRIGIDO"]


def test_claims_reprovadas_preservam_campos_de_constatacao_conforme():
    for tipo, campo in (("CAUSA", "origem"), ("ORIGEM", "origem"), ("CRITICIDADE", "criticidade")):
        entrada = _entrada_base()
        entrada["claims"][0]["tipo"] = tipo
        patologia = entrada["resultado"]["patologias"][0]
        patologia["constatacao"]["situacao"] = "CONFORME"
        valor_antes = copy.deepcopy(patologia[campo])

        final, _ = autocorrigir(**entrada)

        assert final["patologias"][0][campo] == valor_antes


def test_achados_nao_rebaixam_patologia_sem_relacao_com_o_alvo():
    entrada = _entrada_base()
    entrada["claims"] = []
    entrada["auditorias"] = []
    patologia = entrada["resultado"]["patologias"][0]
    patologia["constatacoes"] = []
    patologia["analise_causal"]["fundamentos"] = []
    patologia["normas_relacionadas"] = [
        {
            "id": "NOR-SEGURA",
            "authority": "FONTE_PRIMARIA_OFICIAL",
            "classificacao_fonte": "FONTE_PRIMARIA_OFICIAL",
        }
    ]
    entrada["resultado"]["questoes_saneadas"] = [
        {
            "id": "QT-001",
            "status": "NAO_SANEADA",
            "conclusao": None,
            "ressalvas": [],
            "patologias": ["PAT-AUSENTE"],
        }
    ]
    entrada["achados"] = [
        {"tipo": "ANALISE_CAUSAL_NAO_EXECUTADA", "claim_id": "QT-001"},
        {"tipo": "AUTORIDADE_NORMATIVA_AUTODECLARADA", "claim_id": "EVD-AUSENTE"},
        {"tipo": "OBS_NEGADA_COM_RESULTADO_OBSERVADO", "claim_id": "OBS-AUSENTE"},
        {"tipo": "NORMA_USADA_COMO_FATO_DO_CASO", "claim_id": "NOR-AUSENTE"},
    ]

    final, _ = autocorrigir(**entrada)

    patologia_final = final["patologias"][0]
    assert patologia_final["origem"] == "ENDOGENA_CONSTRUTIVA"
    assert patologia_final["causa"] == patologia["causa"]
    assert patologia_final["normas_relacionadas"][0]["authority"] == "FONTE_PRIMARIA_OFICIAL"

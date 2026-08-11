"""Planeja o laudo judicial sem produzir ou recalcular conclusão técnica."""

from __future__ import annotations


MODELOS = {"VICIOS_CONSTRUTIVOS": "LAUDO_VICIOS_CONSTRUTIVOS_V1"}
ESTRUTURA_VICIOS = (
    ("1", "CONSIDERAÇÕES GERAIS", ("1.1 Identificação do Processo", "1.2 Qualificação do Perito Nomeado", "1.3 Preâmbulo", "1.4 Síntese Processual e Delimitação do Tema Controvertido", "1.5 Objeto da Perícia", "1.6 Objetivo da Perícia")),
    ("2", "METODOLOGIA E NORMAS TÉCNICAS", ("2.1 Metodologia Adotada", "2.2 Normas Técnicas Aplicáveis", "2.3 Definições Técnicas Necessárias", "2.4 Classificação das Origens", "2.5 Classificação da Criticidade", "2.6 Limitações da Inspeção")),
    ("3", "VISTORIA", ("3.1 Dados da Diligência Pericial", "3.2 Condições Gerais da Edificação", "3.3 Análise dos Sistemas Construtivos")),
    ("4", "CONCLUSÃO", ("4.1 Avaliação das Classificações", "4.2 Quadro-Resumo das Manifestações Analisadas", "4.3 Síntese Conclusiva do Tema Controvertido")),
    ("5", "QUESITOS", ()), ("6", "ORÇAMENTO", ()),
    ("7", "REFERÊNCIAS BIBLIOGRÁFICAS", ()), ("8", "ENCERRAMENTO", ()),
)


def _texto(valor):
    return valor.get("texto") if isinstance(valor, dict) else valor


def _tipo_pericia(delimitacao, motor):
    return (delimitacao.get("tipo_pericia") or motor.get("tipo_pericia") or
            motor.get("analise_final", {}).get("tipo_pericia"))


def planejar(processo, delimitacao, motor):
    gate = motor.get("gate") or motor.get("analise_final", {}).get("gate_redacao")
    final = motor.get("analise_final", motor)
    tipo = _tipo_pericia(delimitacao, motor)
    modelo = MODELOS.get(tipo)
    patologias = final.get("patologias", [])
    questoes = final.get("questoes_saneadas", delimitacao.get("questoes_tecnicas", []))
    quesitos = delimitacao.get("quesitos", [])
    ressalvas = list(dict.fromkeys(delimitacao.get("ressalvas", []) + final.get("ressalvas", [])))
    secoes = []
    unidades = []
    for pat in patologias:
        qts = [q["id"] for q in questoes if pat["id"] in q.get("patologias", [])]
        ques = [q["id"] for q in quesitos if pat["id"] in q.get("patologias_relacionadas", []) or set(q.get("questoes_tecnicas", [])) & set(qts)]
        evidencias = pat.get("evidencias", []) + pat.get("constatacoes", []) + pat.get("medicoes", [])
        evidencias += [n["id"] for n in pat.get("normas_relacionadas", []) if n.get("verificada")]
        unidades.append({"pat_id": pat["id"], "qt_ids": list(dict.fromkeys(qts)), "que_ids": list(dict.fromkeys(ques)),
                         "evidencias_permitidas": list(dict.fromkeys(evidencias)),
                         "grau_certeza": pat.get("analise_causal", {}).get("grau_certeza", "INCONCLUSIVO"),
                         "ressalvas_obrigatorias": list(dict.fromkeys(pat.get("ressalvas", []) + pat.get("analise_causal", {}).get("limitacoes", [])))})
    if modelo:
        for numero, titulo, subsecoes in ESTRUTURA_VICIOS:
            secoes.append({
                "id": f"SEC-{int(numero):03d}", "numero": numero, "titulo": titulo,
                "subsecoes": list(subsecoes), "finalidade": {
                    "1": "Delimitar encargo, controvérsia, objeto e objetivo sem matéria jurídica.",
                    "2": "Expor somente método, critérios e normas efetivamente aplicáveis.",
                    "3": "Registrar diligência, condições e análises por sistema.",
                    "4": "Consolidar PAT e responder ao tema controvertido.",
                    "5": "Responder quesitos pertinentes sem criar conclusão nova.",
                    "6": "Integrar apenas itens declarados elegíveis pelo Motor.",
                    "7": "Listar exclusivamente referências efetivamente usadas.",
                    "8": "Preparar os dados semânticos de encerramento.",
                }[numero],
                "pat_ids": [p["id"] for p in patologias],
                "qt_ids": [q["id"] for q in questoes if q.get("id")],
                "que_ids": [q["id"] for q in quesitos if q.get("id")],
                "evidencias_permitidas": list(dict.fromkeys(e for p in patologias for e in
                    p.get("evidencias", []) + p.get("constatacoes", []) + p.get("medicoes", []))),
                "grau_certeza": "NAO_APLICAVEL", "ressalvas_obrigatorias": ressalvas,
            })
    bloqueado = gate == "BLOQUEADO_PARA_REDACAO" or modelo is None
    return {
        "schema_version": "1.1.0", "status": "BLOQUEADO" if bloqueado else "PLANEJADO",
        "gate_tecnico": gate or "BLOQUEADO_PARA_REDACAO", "tipo_pericia": tipo or "NAO_INFORMADO",
        "modelo_documental": modelo, "numero_processo": processo.get("numero_processo"),
        "sintese_processual": _texto(delimitacao.get("sintese_processual")),
        "tema_controvertido": _texto(delimitacao.get("tema_controvertido")),
        "objeto": _texto(delimitacao.get("objeto")), "objetivo": _texto(delimitacao.get("objetivo")),
        "secoes": secoes, "unidades_patologia": unidades,
        "metricas": {"patologias": len(patologias), "questoes_tecnicas": len(questoes), "quesitos_influentes": len(quesitos)},
    }

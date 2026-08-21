"""Reduz claims reprovadas sem apagar constatações sustentadas."""

from __future__ import annotations

from copy import deepcopy


REPROVADOS = {"INSUFFICIENT", "UNSUBSTANTIATED", "INTERPOLATED", "CONTRADICTED"}


def _registrar_claim(historico, auditorias, claim, antes, depois, acao, motivo):
    historico.append(
        {
            "id": f"AUT-{len(historico) + 1:03d}",
            "alvo": claim["id"],
            "claim": claim["id"],
            "valor_antes": str(antes),
            "veredito": next(
                auditoria["veredito"] for auditoria in auditorias if auditoria["claim_id"] == claim["id"]
            ),
            "evidencia": ",".join(
                next(auditoria["evidencias"] for auditoria in auditorias if auditoria["claim_id"] == claim["id"])
            ),
            "acao": acao,
            "valor_depois": str(depois),
            "motivo": motivo,
            "achado_originador": claim["id"],
        }
    )


def _registrar_achado(historico, achado, alvo, antes, depois, acao, motivo):
    if antes == depois:
        return
    historico.append(
        {
            "id": f"AUT-{len(historico) + 1:03d}",
            "alvo": alvo,
            "claim": achado.get("claim_id"),
            "valor_antes": str(antes),
            "veredito": None,
            "evidencia": ",".join(map(str, achado.get("evidencias", []))),
            "acao": acao,
            "valor_depois": str(depois),
            "motivo": motivo,
            "achado_originador": achado.get("tipo"),
        }
    )


def _reduzir_causa_ou_mecanismo(patologia, tipo):
    antes = patologia["causa"] if tipo == "CAUSA" else patologia["mecanismo"]
    if tipo == "CAUSA":
        patologia["causa"] = None
        patologia["analise_causal"]["causa_provavel"] = None
        if patologia.get("constatacao", {}).get("situacao") not in {"CONFORME", "NAO_CONSTATADA"}:
            patologia["origem"] = "INCONCLUSIVA"
            patologia["vicio_construtivo"].update(
                {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
            )
            patologia["reparabilidade"] = "NECESSITA_INVESTIGACAO"
            patologia["recomendacao"].update({"necessaria": False, "descricao": None})
            patologia["elegibilidade_orcamento"] = "PENDENTE"
    else:
        patologia["mecanismo"] = None
    patologia["analise_causal"]["grau_certeza"] = "INCONCLUSIVO"
    patologia["conclusao_tecnica"] = (
        "A manifestação foi constatada, mas os elementos disponíveis não permitem "
        "individualizar com segurança sua causa."
    )
    ressalva = "Causalidade inconclusiva após auditoria do suporte probatório."
    if ressalva not in patologia["ressalvas"]:
        patologia["ressalvas"].append(ressalva)
    return (
        antes,
        None,
        "REDUZIR_CLAIM",
        "Suporte insuficiente para manter formulação causal específica.",
    )


def _reduzir_origem(patologia):
    antes = patologia["origem"]
    if patologia.get("constatacao", {}).get("situacao") not in {"CONFORME", "NAO_CONSTATADA"}:
        patologia["origem"] = "INCONCLUSIVA"
        patologia["vicio_construtivo"].update(
            {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
        )
        patologia["elegibilidade_orcamento"] = "PENDENTE"
    return antes, patologia["origem"], "REDUZIR_ORIGEM", "Origem dependia de claim não sustentada."


def _reduzir_criticidade(patologia):
    antes = patologia["criticidade"]
    if patologia.get("constatacao", {}).get("situacao") not in {"CONFORME", "NAO_CONSTATADA"}:
        patologia["criticidade"] = "INCONCLUSIVA"
    return antes, patologia["criticidade"], "REDUZIR_CRITICIDADE", "Criticidade sem fundamento suficiente."


def _reduzir_vicio_construtivo(patologia):
    antes = patologia["vicio_construtivo"]["caracterizado"]
    patologia["vicio_construtivo"].update(
        {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
    )
    patologia["elegibilidade_orcamento"] = "PENDENTE"
    return (
        antes,
        False,
        "REMOVER_CARACTERIZACAO",
        "Caracterização dependia de origem/causa não sustentada.",
    )


def _reduzir_conformidade_normativa(patologia):
    antes = len(patologia["normas_relacionadas"])
    patologia["normas_relacionadas"] = [
        norma
        for norma in patologia["normas_relacionadas"]
        if norma.get("verificada") and norma.get("aplicabilidade_temporal") != "NAO_APLICAVEL"
    ]
    return (
        antes,
        len(patologia["normas_relacionadas"]),
        "REMOVER_FUNDAMENTO_NORMATIVO",
        "Norma ou requisito não verificável.",
    )


def _aplicar_reducao_claim(patologia, tipo):
    if tipo in {"CAUSA", "MECANISMO"}:
        return _reduzir_causa_ou_mecanismo(patologia, tipo)
    if tipo == "ORIGEM":
        return _reduzir_origem(patologia)
    if tipo == "CRITICIDADE":
        return _reduzir_criticidade(patologia)
    if tipo == "VICIO_CONSTRUTIVO":
        return _reduzir_vicio_construtivo(patologia)
    if tipo == "CONFORMIDADE_NORMATIVA":
        return _reduzir_conformidade_normativa(patologia)
    return None


def _reduzir_claims(por_claim, por_patologia, auditorias, historico):
    for auditoria in auditorias:
        if auditoria["veredito"] not in REPROVADOS:
            continue
        claim = por_claim[auditoria["claim_id"]]
        patologia = por_patologia.get(claim.get("patologia"))
        if not patologia:
            continue
        reducao = _aplicar_reducao_claim(patologia, claim["tipo"])
        if reducao is not None:
            _registrar_claim(historico, auditorias, claim, *reducao)


def _alvo_achado(achado):
    return achado.get("claim_id") or next(
        (
            evidencia
            for evidencia in achado.get("evidencias", [])
            if str(evidencia).startswith(("OBS-", "NOR-", "PAT-", "QT-"))
        ),
        None,
    )


def _corrigir_capacidade_motor(final, por_patologia, achado, alvo):
    qid = alvo or next(
        (evidencia for evidencia in achado.get("evidencias", []) if str(evidencia).startswith("QT-")),
        None,
    )
    questao = next((item for item in final.get("questoes_saneadas", []) if item.get("id") == qid), None)
    if questao:
        questao["status"] = "INCONCLUSIVA_POR_LIMITACAO"
        questao["conclusao"] = "Análise causal não executada; conteúdo indisponível para redação técnica."
        questao["ressalvas"] = ["BLOQUEIO_INTERNO_POR_CAPACIDADE_DO_MOTOR"]
        for patologia_id in questao.get("patologias", []):
            patologia = por_patologia.get(patologia_id)
            if (
                patologia
                and patologia.get("analise_causal", {}).get("status_capacidade")
                == "MOTOR_CAUSAL_NAO_IMPLEMENTADO"
                and patologia.get("constatacao", {}).get("situacao") not in {"CONFORME", "NAO_CONSTATADA"}
            ):
                patologia["causa"] = None
                patologia["mecanismo"] = None
                patologia["origem"] = "INCONCLUSIVA"
                patologia["vicio_construtivo"].update(
                    {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
                )
                patologia["elegibilidade_orcamento"] = "PENDENTE"
def _corrigir_origem_endogena(por_patologia, alvo):
    patologia = por_patologia[alvo]
    patologia["origem"] = "INCONCLUSIVA"
    patologia["vicio_construtivo"].update(
        {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
    )
    patologia["recomendacao"].update({"necessaria": False, "descricao": None})
    patologia["reparabilidade"] = "NECESSITA_INVESTIGACAO"
    patologia["elegibilidade_orcamento"] = "PENDENTE"


def _corrigir_negacao(final, historico, achado, alvo):
    for evidencia in final.get("catalogo_evidencias", []):
        if evidencia.get("id") == alvo:
            antes = deepcopy(evidencia)
            negados = {
                aspecto.get("aspecto")
                for aspecto in evidencia.get("auditoria_aspectos", [])
                if aspecto.get("polaridade") == "NEGADO"
            }
            evidencia["aspectos_suportados"] = [
                aspecto for aspecto in evidencia.get("aspectos_suportados", []) if aspecto not in negados
            ]
            evidencia["aspectos_contraditos"] = sorted(
                set(evidencia.get("aspectos_contraditos", [])) | negados
            )
            _registrar_achado(
                historico,
                achado,
                alvo,
                antes,
                evidencia,
                "CORRIGIR_POLARIDADE",
                "Aspecto negado não pode permanecer como suporte positivo.",
            )


def _corrigir_autoridade(final, historico, achado, alvo):
    for evidencia in final.get("catalogo_evidencias", []):
        if evidencia.get("id") == alvo:
            antes = deepcopy(evidencia)
            evidencia["authority"] = "NAO_DETERMINADA"
            _registrar_achado(
                historico,
                achado,
                alvo,
                antes,
                evidencia,
                "REMOVER_AUTORIDADE_AUTODECLARADA",
                "Autoridade exige proveniência verificável.",
            )
    for patologia in final.get("patologias", []):
        for norma in patologia.get("normas_relacionadas", []):
            if (
                norma.get("authority") in {"FONTE_PRIMARIA_OFICIAL", "FONTE_OFICIAL_VERIFICADA"}
                and norma.get("classificacao_fonte") != "FONTE_PRIMARIA_OFICIAL"
            ):
                norma["authority"] = "NAO_DETERMINADA"


def _corrigir_observacao_negada(final, historico, achado, alvo):
    for evidencia in final.get("catalogo_evidencias", []):
        if evidencia.get("id") == alvo:
            antes = deepcopy(evidencia)
            evidencia["resultado"] = "NAO_CONSTATADO_NA_VISTORIA"
            _registrar_achado(
                historico,
                achado,
                alvo,
                antes,
                evidencia,
                "CORRIGIR_RESULTADO_NEGADO",
                "Observação negada não pode permanecer observada.",
            )
    for patologia in final.get("patologias", []):
        if alvo in patologia.get("constatacoes", []):
            patologia["constatacao"]["situacao"] = "NAO_CONSTATADA"
            patologia["causa"] = None
            patologia["origem"] = "NAO_APLICAVEL"
            patologia["vicio_construtivo"].update(
                {"caracterizado": False, "tipo": "NAO_APLICAVEL", "fundamentacao": None}
            )
            patologia["elegibilidade_orcamento"] = "NAO_ELEGIVEL"
            patologia["conclusao_tecnica"] = (
                "A manifestação não foi constatada na vistoria, sem equivaler a afirmação de inexistência."
            )


def _corrigir_norma_como_fato(final, historico, achado, alvo):
    normativos = {
        "REQUISITO_NORMATIVO_VERIFICADO",
        "METODO_NORMATIVO_VERIFICADO",
        "CRITERIO_NORMATIVO_VERIFICADO",
        "DEFINICAO_NORMATIVA_VERIFICADA",
        "ESCOPO_NORMATIVO_VERIFICADO",
        "APLICABILIDADE_TEMPORAL",
    }
    for evidencia in final.get("catalogo_evidencias", []):
        if evidencia.get("id") == alvo:
            antes = deepcopy(evidencia)
            evidencia["aspectos_suportados"] = [
                aspecto for aspecto in evidencia.get("aspectos_suportados", []) if aspecto in normativos
            ]
            _registrar_achado(
                historico,
                achado,
                alvo,
                antes,
                evidencia,
                "RESTRINGIR_NORMA_A_ASPECTO_NORMATIVO",
                "Norma não prova fato físico do caso.",
            )
    for patologia in final.get("patologias", []):
        if alvo in patologia.get("analise_causal", {}).get("fundamentos", []):
            patologia["analise_causal"]["fundamentos"].remove(alvo)
            patologia["causa"] = None
            patologia["origem"] = "INCONCLUSIVA"
            patologia["vicio_construtivo"].update(
                {"caracterizado": False, "tipo": "INCONCLUSIVO", "fundamentacao": None}
            )
            patologia["recomendacao"].update({"necessaria": False, "descricao": None})
            patologia["elegibilidade_orcamento"] = "PENDENTE"


def _aplicar_achados(final, por_patologia, achados, historico):
    for achado in achados or []:
        estado_antes_achado = deepcopy(final)
        tipo = achado.get("tipo")
        alvo = _alvo_achado(achado)
        if tipo in {"QT_CAUSAL_SEM_CAPACIDADE_DO_MOTOR", "ANALISE_CAUSAL_NAO_EXECUTADA"}:
            _corrigir_capacidade_motor(final, por_patologia, achado, alvo)
        if tipo == "ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA" and alvo in por_patologia:
            _corrigir_origem_endogena(por_patologia, alvo)
        if tipo == "NEGACAO_CONVERTIDA_EM_FATO":
            _corrigir_negacao(final, historico, achado, alvo)
        if tipo == "AUTORIDADE_NORMATIVA_AUTODECLARADA":
            _corrigir_autoridade(final, historico, achado, alvo)
        if tipo == "OBS_NEGADA_COM_RESULTADO_OBSERVADO":
            _corrigir_observacao_negada(final, historico, achado, alvo)
        if tipo == "NORMA_USADA_COMO_FATO_DO_CASO":
            _corrigir_norma_como_fato(final, historico, achado, alvo)
        _registrar_achado(
            historico,
            achado,
            alvo or "ANALISE",
            estado_antes_achado,
            final,
            "APLICAR_CORRECAO_DETECTOR",
            "Correção determinística motivada por achado reproduzível.",
        )


def _finalizar(final, por_patologia, historico):
    estado_antes_finalizacao = deepcopy(final)
    final["estado_analise"] = "PAT_FINAL"
    final["status_execucao"] = "ANALISE_CONCLUIDA"
    for questao in final.get("questoes_saneadas", []):
        patologias = [por_patologia[item] for item in questao["patologias"] if item in por_patologia]
        inconclusiva = any(
            patologia.get("constatacao", {}).get("situacao") in {"ANOMALIA", "FALHA", "INCONCLUSIVA"}
            and not patologia.get("causa")
            for patologia in patologias
        )
        if inconclusiva and questao.get("status") not in {"SANEADA", "INCONCLUSIVA_POR_LIMITACAO"}:
            questao["status"] = "SANEADA_COM_RESSALVA"
            questao["ressalvas"] = ["Causalidade inconclusiva após auditoria."]
            questao["conclusao"] = (
                "A questão pode ser tratada quanto à constatação, com ressalva de que a causa específica "
                "permanece inconclusiva."
            )
    for cobertura in final.get("cobertura_quesitos", []):
        if cobertura["status"] != "MATERIA_JURIDICA" and cobertura.get("patologias"):
            cobertura["status"] = (
                "RESPONDIVEL_COM_RESSALVA"
                if any(
                    por_patologia[item].get("ressalvas")
                    for item in cobertura["patologias"]
                    if item in por_patologia
                )
                else "RESPONDIVEL"
            )
    _registrar_achado(
        historico,
        {"tipo": "FINALIZACAO_AUTOCORRECAO", "evidencias": []},
        "PAT_FINAL",
        estado_antes_finalizacao,
        final,
        "FINALIZAR_ESTADO_CORRIGIDO",
        "Estado final e projeções derivadas recalculados após as correções.",
    )


def autocorrigir(resultado, claims, auditorias, achados=None):
    final = deepcopy(resultado)
    por_claim = {claim["id"]: claim for claim in claims}
    por_patologia = {patologia["id"]: patologia for patologia in final.get("patologias", [])}
    historico = []
    _reduzir_claims(por_claim, por_patologia, auditorias, historico)
    _aplicar_achados(final, por_patologia, achados, historico)
    _finalizar(final, por_patologia, historico)
    return final, historico

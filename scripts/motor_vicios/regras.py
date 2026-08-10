"""Regras puras de classificação, sem conclusão por palavra-chave."""

def situacao(observacoes):
    resultados={o.get("resultado") for o in observacoes}
    if "FALHA" in resultados:return "FALHA"
    if "OBSERVADO" in resultados:return "ANOMALIA"
    if "CONFORME" in resultados:return "CONFORME"
    if "NAO_CONSTATADO_NA_VISTORIA" in resultados:return "NAO_CONSTATADA"
    return "INCONCLUSIVA"

def inferir_origem(causa,evidencias):
    """Infere origem pela convergencia de fatos independentes, nao por rotulo pronto."""
    aspectos={a for e in evidencias for a in e.get("aspectos_suportados",[])}
    def independentes(sinais):
        fontes={tuple(e.get("proveniencia",[])) or (e.get("id"),) for e in evidencias if set(e.get("aspectos_suportados",[]))&set(sinais)}
        return len(fontes)>=2
    grupos=[]
    dimensoes={"PROJETO_CONSTRUTIVO_DOCUMENTADO","MATERIAL_CONSTRUTIVO_DOCUMENTADO","ESPECIFICACAO_CONSTRUTIVA_DOCUMENTADA","DETALHE_CONSTRUTIVO_DOCUMENTADO","PROCEDIMENTO_EXECUTIVO_DOCUMENTADO","CONTROLE_TECNOLOGICO_DOCUMENTADO","DOCUMENTACAO_OBRA_VERIFICADA"}
    divergencias={"EXECUCAO_DIVERGENTE_DOCUMENTADA","NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA"}
    if causa and aspectos&dimensoes and aspectos&divergencias and independentes(dimensoes|divergencias):grupos.append("ENDOGENA_CONSTRUTIVA")
    if {"IMPACTO_REGISTRADO","INTERVENCAO_TERCEIRO_DOCUMENTADA"}<=aspectos and independentes({"IMPACTO_REGISTRADO","INTERVENCAO_TERCEIRO_DOCUMENTADA"}):grupos.append("EXOGENA")
    if "COMPORTAMENTO_FUNCIONAL_OBSERVADO" in aspectos and independentes({"COMPORTAMENTO_FUNCIONAL_OBSERVADO"}):grupos.append("FUNCIONAL")
    if {"MANUTENCAO_AUSENTE_DOCUMENTADA","USO_INADEQUADO_DOCUMENTADO"}<=aspectos and independentes({"MANUTENCAO_AUSENTE_DOCUMENTADA","USO_INADEQUADO_DOCUMENTADO"}):grupos.append("USO_OPERACAO_MANUTENCAO")
    grupos=list(dict.fromkeys(grupos))
    return "MISTA" if len(grupos)>1 else grupos[0] if grupos else "INCONCLUSIVA"

def avaliar_consequencias(sit,evidencias):
    aspectos={a for e in evidencias for a in e.get("aspectos_suportados",[])};ids=[e["id"] for e in evidencias]
    mapa={"seguranca":"RISCO_SEGURANCA_REGISTRADO","salubridade":"RISCO_SALUBRIDADE_REGISTRADO","funcionalidade":"PERDA_FUNCIONAL_REGISTRADA","desempenho":"PERDA_FUNCIONAL_REGISTRADA","estanqueidade":"UMIDADE_MEDIDA","durabilidade":"DEGRADACAO_RELEVANTE_REGISTRADA","estetica":"REPERCUSSAO_LOCALIZADA_REGISTRADA","usabilidade":"PERDA_FUNCIONAL_REGISTRADA","evolucao":"EVOLUCAO_REGISTRADA","extensao":"EXTENSAO_REGISTRADA"}
    saida={}
    for nome,sinal in mapa.items():
        if sit in {"CONFORME","NAO_CONSTATADA"}:status="NAO_APLICAVEL"
        elif sinal in aspectos:status="PRESENTE"
        else:status="INCONCLUSIVA"
        saida[nome]={"status":status,"evidencias":ids if status=="PRESENTE" else [],"fundamentacao":f"Aspecto probatório {sinal} identificado." if status=="PRESENTE" else None,"confianca":"MEDIA" if status=="PRESENTE" else "BAIXA"}
    return saida

def derivar_criticidade(sit,consequencias):
    if sit in {"CONFORME","NAO_CONSTATADA"}:return "NAO_APLICAVEL",None
    if any(consequencias[k]["status"]=="PRESENTE" for k in ("seguranca","salubridade")):return "CRITICA","Risco material de segurança ou salubridade tecnicamente registrado."
    if any(consequencias[k]["status"]=="PRESENTE" for k in ("funcionalidade","desempenho","durabilidade","estanqueidade")):return "MEDIA","Repercussão relevante de desempenho, funcionalidade ou durabilidade registrada."
    if consequencias["estetica"]["status"]=="PRESENTE":return "MINIMA","Repercussão localizada sem impacto material adicional registrado."
    return "INCONCLUSIVA",None

def estruturar_reparo(causa,sistema,evidencias):
    aspectos={a for e in evidencias for a in e.get("aspectos_suportados",[])}
    if not causa or not ({"DETALHE_CONSTRUTIVO_DOCUMENTADO","EXECUCAO_DIVERGENTE_DOCUMENTADA"}<=aspectos):return None
    return {"objetivo":"Restabelecer o desempenho afetado","sistema":sistema,"escopo":"Intervir no trecho comprovadamente afetado","etapas_gerais":["confirmar extensao","remover materiais comprometidos","executar solucao compatível com o detalhe verificado","verificar desempenho"],"mecanismo_ou_causa_tratada":causa,"limitacoes":["Dimensionamento executivo e quantitativos dependem de levantamento proprio"],"investigacao_adicional":True}

def tipo_vicio(evidencias,vicio):
    if not vicio:return "NAO_APLICAVEL"
    aspectos={a for e in evidencias for a in e.get("aspectos_suportados",[])}
    if "APARENTE_EM_INSPECAO" in aspectos:return "APARENTE"
    if "NAO_APARENTE_EM_INSPECAO" in aspectos:return "OCULTO"
    return "INCONCLUSIVO"

def classificacoes(sit, causalidade=None):
    causalidade=causalidade or {}
    origem=causalidade.get("origem") if causalidade.get("evidencias") else None
    permitidas={"ENDOGENA_CONSTRUTIVA","EXOGENA","FUNCIONAL","USO_OPERACAO_MANUTENCAO","MISTA","INCONCLUSIVA","NAO_APLICAVEL"}
    origem=origem if origem in permitidas else "INCONCLUSIVA"
    if sit in {"CONFORME","NAO_CONSTATADA"}:origem="NAO_APLICAVEL"
    criticidade=causalidade.get("criticidade") if causalidade.get("fundamentacao_criticidade") else None
    if criticidade not in {"CRITICA","MEDIA","MINIMA","INCONCLUSIVA","NAO_APLICAVEL"}:criticidade="INCONCLUSIVA"
    if sit in {"CONFORME","NAO_CONSTATADA"}:criticidade="NAO_APLICAVEL"
    vicio=bool(sit in {"ANOMALIA","FALHA"} and origem=="ENDOGENA_CONSTRUTIVA" and causalidade.get("causa") and causalidade.get("evidencias"))
    reparo=causalidade.get("reparo")
    reparo_completo=isinstance(reparo,dict) and all(reparo.get(k) not in (None,"",[]) for k in ("objetivo","sistema","escopo","etapas_gerais","mecanismo_ou_causa_tratada","limitacoes"))
    elegivel="ELEGIVEL_ORCAMENTO_VICIO" if vicio and reparo_completo else "NAO_ELEGIVEL" if sit in {"CONFORME","NAO_CONSTATADA"} or origem in {"EXOGENA","FUNCIONAL","USO_OPERACAO_MANUTENCAO"} else "PENDENTE"
    return origem,criticidade,vicio,elegivel

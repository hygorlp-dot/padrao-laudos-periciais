"""Auditoria profunda baseada em claims já extraídas e seus vereditos."""
from __future__ import annotations
import re
NEGACOES=(r"\b(não|nao)\b",r"\bausência de\b",r"\bausencia de\b",r"\binexistência de\b",r"\binexistencia de\b",r"\bsem\b",r"\binexistente\b")
PREFIXOS_EXISTENCIA=(r"^há\s+",r"^ha\s+",r"^existe\s+",r"^presença de\s+",r"^presenca de\s+")
def _polaridade(texto):
    base=re.sub(r"\s+"," ",texto.strip().lower());negado=any(re.search(p,base) for p in NEGACOES)
    for padrao in (*NEGACOES,*PREFIXOS_EXISTENCIA):base=re.sub(padrao," ",base.strip())
    return negado,re.sub(r"\s+"," ",base).strip(" .,:;")
def executar_deep_audit(claims_auditadas,resultado=None):
    achados=[]
    catalogo={e.get("id"):e for e in (resultado or {}).get("catalogo_evidencias",[])};dimensoes={"PROJETO_CONSTRUTIVO_DOCUMENTADO","MATERIAL_CONSTRUTIVO_DOCUMENTADO","ESPECIFICACAO_CONSTRUTIVA_DOCUMENTADA","DETALHE_CONSTRUTIVO_DOCUMENTADO","PROCEDIMENTO_EXECUTIVO_DOCUMENTADO","CONTROLE_TECNOLOGICO_DOCUMENTADO","DOCUMENTACAO_OBRA_VERIFICADA"};divergencias={"EXECUCAO_DIVERGENTE_DOCUMENTADA","NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA"}
    for claim in claims_auditadas:
        if claim["saliencia"]=="LOAD_BEARING" and claim["veredito"] in {"INSUFFICIENT","INTERPOLATED","UNSUBSTANTIATED","CONTRADICTED"}:
            achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CONCLUSAO_EXCEDE_EVIDENCIA","severidade":"CRITICO","claim_id":claim["claim_id"],"veredito":claim["veredito"],"acao":"Reduzir a conclusão ao conteúdo efetivamente sustentado."})
        elif claim["saliencia"]=="LOAD_BEARING" and claim["veredito"]=="UNVERIFIABLE":
            achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CLAIM_MATERIAL_NAO_VERIFICAVEL","severidade":"IMPORTANTE","claim_id":claim["claim_id"],"veredito":claim["veredito"],"acao":"Tratar como inconclusiva por limitação; não presumir falsidade."})
        elif claim["saliencia"]=="LOAD_BEARING" and claim["veredito"]=="WEAKLY_GROUNDED":
            achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CLAIM_MATERIAL_COM_SUPORTE_FRACO","severidade":"IMPORTANTE","claim_id":claim["claim_id"],"veredito":claim["veredito"],"acao":"Ressalvar explicitamente e impedir formulação categórica."})
    for pat in (resultado or {}).get("patologias",[]):
        if pat.get("causa") and not pat.get("analise_causal",{}).get("fundamentos"):achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CAUSALIDADE_INSUFICIENTE","severidade":"CRITICO","claim_id":pat["id"],"veredito":"INSUFFICIENT","acao":"Retirar causa específica ou obter fundamento rastreável."})
        if any(str(x).startswith("MOD-") for x in pat.get("analise_causal",{}).get("fundamentos",[])):achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CASO_ANTERIOR_USADO_COMO_RESULTADO_FATICO","severidade":"CRITICO","claim_id":pat["id"],"veredito":"UNSUBSTANTIATED","acao":"Remover caso anterior da fundamentação factual."})
        for norma in pat.get("normas_relacionadas",[]):
            if norma.get("item") and not norma.get("verificada"):achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"EXTRAPOLACAO_NORMATIVA","severidade":"CRITICO","claim_id":pat["id"],"veredito":"UNVERIFIABLE","acao":"Remover o item específico até consulta e verificação da fonte."})
            if norma.get("authority") in {"FONTE_PRIMARIA_OFICIAL","FONTE_OFICIAL_VERIFICADA"} and norma.get("classificacao_fonte")!="FONTE_PRIMARIA_OFICIAL":achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"AUTORIDADE_NORMATIVA_AUTODECLARADA","severidade":"CRITICO","claim_id":pat["id"],"veredito":"UNVERIFIABLE","acao":"Remover autoridade oficial indevida e verificar a fonte."})
        ligadas=[catalogo.get(x,{}) for x in pat.get("evidencias",[])];aspectos={a for e in ligadas for a in e.get("aspectos_suportados",[])};fontes={tuple(e.get("proveniencia",[])) or (e.get("id"),) for e in ligadas if set(e.get("aspectos_suportados",[]))&(dimensoes|divergencias)}
        if pat.get("origem")=="ENDOGENA_CONSTRUTIVA" and not (aspectos&dimensoes and aspectos&divergencias and len(fontes)>=2):achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA","severidade":"CRITICO","claim_id":pat["id"],"veredito":"UNSUBSTANTIATED","acao":"Reduzir origem a inconclusiva e rever vício, reparo e orçamento."})
    por_pat={p.get("id"):p for p in (resultado or {}).get("patologias",[])}
    for qt in (resultado or {}).get("questoes_saneadas",[]):
        ligados=[por_pat[x] for x in qt.get("patologias",[]) if x in por_pat]
        sem_capacidade=any(p.get("analise_causal",{}).get("status_capacidade")=="MOTOR_CAUSAL_NAO_IMPLEMENTADO" for p in ligados)
        if qt.get("status")=="INCONCLUSIVA_POR_LIMITACAO" and sem_capacidade:achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"ANALISE_CAUSAL_NAO_EXECUTADA","severidade":"CRITICO","claim_id":qt.get("id"),"veredito":"UNVERIFIABLE","acao":"Bloquear a redação até execução por módulo causal especializado validado."})
    for evidencia in (resultado or {}).get("catalogo_evidencias",[]):
        negados={a.get("aspecto") for a in evidencia.get("auditoria_aspectos",[]) if a.get("polaridade")=="NEGADO"}
        if negados&set(evidencia.get("aspectos_suportados",[])):achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"NEGACAO_CONVERTIDA_EM_FATO","severidade":"CRITICO","claim_id":evidencia.get("id"),"veredito":"CONTRADICTED","acao":"Remover aspecto positivo e preservar a contraevidência."})
        if evidencia.get("authority") in {"FONTE_PRIMARIA_OFICIAL","FONTE_OFICIAL_VERIFICADA"} and evidencia.get("classificacao_fonte")!="FONTE_PRIMARIA_OFICIAL":achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"AUTORIDADE_NORMATIVA_AUTODECLARADA","severidade":"CRITICO","claim_id":evidencia.get("id"),"veredito":"UNVERIFIABLE","acao":"Remover autoridade oficial indevida e verificar a fonte."})
        if evidencia.get("tipo")=="OBSERVACAO" and evidencia.get("resultado")=="OBSERVADO" and negados:achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"OBS_NEGADA_COM_RESULTADO_OBSERVADO","severidade":"CRITICO","claim_id":evidencia.get("id"),"veredito":"CONTRADICTED","acao":"Corrigir a constatação sem convertê-la em inexistência."})
        normativos={"REQUISITO_NORMATIVO_VERIFICADO","METODO_NORMATIVO_VERIFICADO","CRITERIO_NORMATIVO_VERIFICADO","DEFINICAO_NORMATIVA_VERIFICADA","ESCOPO_NORMATIVO_VERIFICADO","APLICABILIDADE_TEMPORAL"};indevidos=set(evidencia.get("aspectos_suportados",[]))-normativos if evidencia.get("tipo")=="NORMA" else set()
        if indevidos:achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"NORMA_USADA_COMO_FATO_DO_CASO","severidade":"CRITICO","claim_id":evidencia.get("id"),"veredito":"UNSUBSTANTIATED","acao":"Remover a norma do suporte fático e reavaliar as inferências dependentes."})
    polaridades={}
    for claim in claims_auditadas:
        negado,base=_polaridade(claim["texto"]);chave=(claim["tipo"],base)
        anterior=polaridades.get(chave)
        if anterior is not None and anterior!=negado:achados.append({"id":f"AUD-DEEP-{len(achados)+1:03d}","tipo":"CONTRADICAO_ENTRE_CLAIMS","severidade":"CRITICO","claim_id":claim["claim_id"],"veredito":"CONTRADICTED","acao":"Reconciliar fontes e manter somente a formulação sustentada."})
        polaridades[chave]=negado
    return achados

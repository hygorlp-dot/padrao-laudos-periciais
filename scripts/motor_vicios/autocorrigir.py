"""Reduz claims reprovadas sem apagar constatações sustentadas."""
from __future__ import annotations
from copy import deepcopy

REPROVADOS={"INSUFFICIENT","UNSUBSTANTIATED","INTERPOLATED","CONTRADICTED"}
def autocorrigir(resultado,claims,auditorias,achados=None):
    final=deepcopy(resultado);por_claim={c["id"]:c for c in claims};por_pat={p["id"]:p for p in final.get("patologias",[])};historico=[]
    def registrar(claim,antes,depois,acao,motivo):
        historico.append({"id":f"AUT-{len(historico)+1:03d}","claim":claim["id"],"valor_antes":str(antes),"veredito":next(a["veredito"] for a in auditorias if a["claim_id"]==claim["id"]),"evidencia":",".join(next(a["evidencias"] for a in auditorias if a["claim_id"]==claim["id"])),"acao":acao,"valor_depois":str(depois),"motivo":motivo})
    for audit in auditorias:
        if audit["veredito"] not in REPROVADOS:continue
        claim=por_claim[audit["claim_id"]];pat=por_pat.get(claim.get("patologia"))
        if not pat:continue
        tipo=claim["tipo"]
        if tipo in {"CAUSA","MECANISMO"}:
            antes=pat["causa"] if tipo=="CAUSA" else pat["mecanismo"]
            if tipo=="CAUSA":
                pat["causa"]=None;pat["analise_causal"]["causa_provavel"]=None
                if pat.get("constatacao",{}).get("situacao") not in {"CONFORME","NAO_CONSTATADA"}:pat["origem"]="INCONCLUSIVA";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["reparabilidade"]="NECESSITA_INVESTIGACAO";pat["recomendacao"].update({"necessaria":False,"descricao":None});pat["elegibilidade_orcamento"]="PENDENTE"
            else:pat["mecanismo"]=None
            pat["analise_causal"]["grau_certeza"]="INCONCLUSIVO";pat["conclusao_tecnica"]="A manifestação foi constatada, mas os elementos disponíveis não permitem individualizar com segurança sua causa.";ress="Causalidade inconclusiva após auditoria do suporte probatório."
            if ress not in pat["ressalvas"]:pat["ressalvas"].append(ress)
            registrar(claim,antes,None,"REDUZIR_CLAIM","Suporte insuficiente para manter formulação causal específica.")
        elif tipo=="ORIGEM":
            antes=pat["origem"]
            if pat.get("constatacao",{}).get("situacao") not in {"CONFORME","NAO_CONSTATADA"}:pat["origem"]="INCONCLUSIVA";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["elegibilidade_orcamento"]="PENDENTE"
            registrar(claim,antes,pat["origem"],"REDUZIR_ORIGEM","Origem dependia de claim não sustentada.")
        elif tipo=="CRITICIDADE":
            antes=pat["criticidade"]
            if pat.get("constatacao",{}).get("situacao") not in {"CONFORME","NAO_CONSTATADA"}:pat["criticidade"]="INCONCLUSIVA"
            registrar(claim,antes,pat["criticidade"],"REDUZIR_CRITICIDADE","Criticidade sem fundamento suficiente.")
        elif tipo=="VICIO_CONSTRUTIVO":
            antes=pat["vicio_construtivo"]["caracterizado"];pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["elegibilidade_orcamento"]="PENDENTE";registrar(claim,antes,False,"REMOVER_CARACTERIZACAO","Caracterização dependia de origem/causa não sustentada.")
        elif tipo=="CONFORMIDADE_NORMATIVA":
            antes=len(pat["normas_relacionadas"]);pat["normas_relacionadas"]=[n for n in pat["normas_relacionadas"] if n.get("verificada") and n.get("aplicabilidade_temporal")!="NAO_APLICAVEL"];registrar(claim,antes,len(pat["normas_relacionadas"]),"REMOVER_FUNDAMENTO_NORMATIVO","Norma ou requisito não verificável.")
    for achado in achados or []:
        tipo=achado.get("tipo");alvo=achado.get("claim_id")
        if tipo in {"QT_CAUSAL_SEM_CAPACIDADE_DO_MOTOR","ANALISE_CAUSAL_NAO_EXECUTADA"}:
            qid=alvo or next((x for x in achado.get("evidencias",[]) if str(x).startswith("QT-")),None)
            qt=next((q for q in final.get("questoes_saneadas",[]) if q.get("id")==qid),None)
            if qt:
                qt["status"]="INCONCLUSIVA_POR_LIMITACAO";qt["conclusao"]="Análise causal não executada; conteúdo indisponível para redação técnica.";qt["ressalvas"]=["BLOQUEIO_INTERNO_POR_CAPACIDADE_DO_MOTOR"]
                for pid in qt.get("patologias",[]):
                    pat=por_pat.get(pid)
                    if pat and pat.get("analise_causal",{}).get("status_capacidade")=="MOTOR_CAUSAL_NAO_IMPLEMENTADO" and pat.get("constatacao",{}).get("situacao") not in {"CONFORME","NAO_CONSTATADA"}:pat["causa"]=None;pat["mecanismo"]=None;pat["origem"]="INCONCLUSIVA";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["elegibilidade_orcamento"]="PENDENTE"
        if tipo=="ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA" and alvo in por_pat:
            pat=por_pat[alvo];pat["origem"]="INCONCLUSIVA";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["recomendacao"].update({"necessaria":False,"descricao":None});pat["reparabilidade"]="NECESSITA_INVESTIGACAO";pat["elegibilidade_orcamento"]="PENDENTE"
        if tipo=="NEGACAO_CONVERTIDA_EM_FATO":
            for evidencia in final.get("catalogo_evidencias",[]):
                if evidencia.get("id")==alvo:
                    negados={a.get("aspecto") for a in evidencia.get("auditoria_aspectos",[]) if a.get("polaridade")=="NEGADO"};evidencia["aspectos_suportados"]=[x for x in evidencia.get("aspectos_suportados",[]) if x not in negados];evidencia["aspectos_contraditos"]=sorted(set(evidencia.get("aspectos_contraditos",[]))|negados)
        if tipo=="AUTORIDADE_NORMATIVA_AUTODECLARADA":
            for evidencia in final.get("catalogo_evidencias",[]):
                if evidencia.get("id")==alvo:evidencia["authority"]="NAO_DETERMINADA"
            for pat in final.get("patologias",[]):
                for norma in pat.get("normas_relacionadas",[]):
                    if norma.get("authority") in {"FONTE_PRIMARIA_OFICIAL","FONTE_OFICIAL_VERIFICADA"} and norma.get("classificacao_fonte")!="FONTE_PRIMARIA_OFICIAL":norma["authority"]="NAO_DETERMINADA"
        if tipo=="OBS_NEGADA_COM_RESULTADO_OBSERVADO":
            for evidencia in final.get("catalogo_evidencias",[]):
                if evidencia.get("id")==alvo:evidencia["resultado"]="NAO_CONSTATADO_NA_VISTORIA"
            for pat in final.get("patologias",[]):
                if alvo in pat.get("constatacoes",[]):pat["constatacao"]["situacao"]="NAO_CONSTATADA";pat["causa"]=None;pat["origem"]="NAO_APLICAVEL";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"NAO_APLICAVEL","fundamentacao":None});pat["elegibilidade_orcamento"]="NAO_ELEGIVEL";pat["conclusao_tecnica"]="A manifestação não foi constatada na vistoria, sem equivaler a afirmação de inexistência."
        if tipo=="NORMA_USADA_COMO_FATO_DO_CASO":
            normativos={"REQUISITO_NORMATIVO_VERIFICADO","METODO_NORMATIVO_VERIFICADO","CRITERIO_NORMATIVO_VERIFICADO","DEFINICAO_NORMATIVA_VERIFICADA","ESCOPO_NORMATIVO_VERIFICADO","APLICABILIDADE_TEMPORAL"}
            for evidencia in final.get("catalogo_evidencias",[]):
                if evidencia.get("id")==alvo:evidencia["aspectos_suportados"]=[x for x in evidencia.get("aspectos_suportados",[]) if x in normativos]
            for pat in final.get("patologias",[]):
                if alvo in pat.get("analise_causal",{}).get("fundamentos",[]):pat["analise_causal"]["fundamentos"].remove(alvo);pat["causa"]=None;pat["origem"]="INCONCLUSIVA";pat["vicio_construtivo"].update({"caracterizado":False,"tipo":"INCONCLUSIVO","fundamentacao":None});pat["recomendacao"].update({"necessaria":False,"descricao":None});pat["elegibilidade_orcamento"]="PENDENTE"
    final["estado_analise"]="PAT_FINAL";final["status_execucao"]="ANALISE_CONCLUIDA"
    for qt in final.get("questoes_saneadas",[]):
        pats=[por_pat[x] for x in qt["patologias"] if x in por_pat];inc=any(p.get("constatacao",{}).get("situacao") in {"ANOMALIA","FALHA","INCONCLUSIVA"} and not p.get("causa") for p in pats)
        # Preserva a separação feita pelo motor entre questões de existência e
        # questões causais, bem como a limitação explícita de capacidade.
        if inc and qt.get("status") not in {"SANEADA","INCONCLUSIVA_POR_LIMITACAO"}:qt["status"]="SANEADA_COM_RESSALVA";qt["ressalvas"]=["Causalidade inconclusiva após auditoria."];qt["conclusao"]="A questão pode ser tratada quanto à constatação, com ressalva de que a causa específica permanece inconclusiva."
    for cob in final.get("cobertura_quesitos",[]):
        if cob["status"]!="MATERIA_JURIDICA" and cob.get("patologias"):cob["status"]="RESPONDIVEL_COM_RESSALVA" if any(por_pat[x].get("ressalvas") for x in cob["patologias"] if x in por_pat) else "RESPONDIVEL"
    return final,historico

"""Detector rápido, determinístico e sem acesso externo."""
from __future__ import annotations
import ast

def detectar_cenario_tautologico(codigo_fonte):
    """Sinaliza testes que comparam diretamente uma entrada consigo mesma."""
    try:
        arvore=ast.parse(codigo_fonte)
    except SyntaxError:
        return [{"tipo":"CENARIO_TAUTOLOGICO","severidade":"CRITICO","evidencias":["CODIGO_FONTE_INVALIDO"]}]
    achados=[]
    for no in ast.walk(arvore):
        if not isinstance(no,ast.Call) or not isinstance(no.func,ast.Attribute) or no.func.attr not in {"assertEqual","assertTrue"}:continue
        argumentos=[ast.dump(x,include_attributes=False) for x in no.args]
        tautologico=no.func.attr=="assertEqual" and len(argumentos)>=2 and argumentos[0]==argumentos[1]
        tautologico=tautologico or (no.func.attr=="assertTrue" and no.args and isinstance(no.args[0],ast.Name) and no.args[0].id in {"entrada","esperado"})
        if tautologico:achados.append({"tipo":"CENARIO_TAUTOLOGICO","severidade":"CRITICO","evidencias":[f"LINHA-{getattr(no,'lineno',0)}"]})
    return achados
def executar_detector(resultado,processo=None,delimitacao=None,vistoria=None,normas=None,ressalvas=None):
    fornecidos={"ALG":processo is not None,"QT":delimitacao is not None,"QUE":delimitacao is not None,"OBS":vistoria is not None,"MED":vistoria is not None,"FOT":vistoria is not None,"NOR":normas is not None,"RES":ressalvas is not None}
    processo,delimitacao,vistoria,normas,ressalvas=processo or {},delimitacao or {},vistoria or {},normas or [],ressalvas or []
    conjuntos={"ALG":{x["id"] for x in processo.get("alegacoes",[])},"QT":{x["id"] for x in delimitacao.get("questoes_tecnicas",[])},"QUE":{x["id"] for x in delimitacao.get("quesitos",[])},"OBS":{x["id"] for x in vistoria.get("observacoes",[])},"MED":{x["id"] for x in vistoria.get("medicoes",[])},"FOT":{x["id"] for x in vistoria.get("fotografias",[])},"NOR":{x.get("id") for x in normas},"RES":{x.get("id") for x in ressalvas}}
    achados=[]
    def add(tipo,evidencias,severidade="CRITICO"):
        chave=(tipo,tuple(sorted(evidencias)))
        if not any(a["chave"]==chave for a in achados):achados.append({"id":f"AUD-RAP-{len(achados)+1:03d}","tipo":tipo,"severidade":severidade,"evidencias":sorted(evidencias),"chave":chave})
    def refs(valores,prefixo,dono):
        valores={valor for valor in valores if valor}
        if valores and not fornecidos[prefixo]:add(f"CATALOGO_{prefixo}_AUSENTE",[dono,*valores],"IMPORTANTE")
        elif fornecidos[prefixo]:
            for valor in valores-conjuntos[prefixo]:add(f"{prefixo}_INEXISTENTE",[dono,valor])
    for pat in resultado.get("patologias",[]):
        pid=pat["id"];refs(pat.get("alegacoes_relacionadas",[]),"ALG",pid);refs(pat.get("constatacoes",[]),"OBS",pid);refs(pat.get("medicoes",[]),"MED",pid);refs(pat.get("constatacao",{}).get("fotografias",[]),"FOT",pid)
        if pat.get("origem")=="ENDOGENA_CONSTRUTIVA" and not pat.get("analise_causal",{}).get("fundamentos"):add("ORIGEM_ENDOGENA_SEM_CADEIA_CAUSAL",[pid])
        vicio=pat.get("vicio_construtivo",{})
        if vicio.get("caracterizado") and pat.get("origem")!="ENDOGENA_CONSTRUTIVA":add("VICIO_SEM_ORIGEM_ENDOGENA",[pid])
        if vicio.get("caracterizado") and vicio.get("tipo")=="NAO_APLICAVEL":add("VICIO_COM_TIPO_NAO_APLICAVEL",[pid])
        if pat.get("criticidade") not in {None,"INCONCLUSIVA","NAO_APLICAVEL"} and not any(pat.get("consequencias",{}).values()):add("CRITICIDADE_SEM_FUNDAMENTO",[pid])
        if pat.get("constatacao",{}).get("situacao")=="CONFORME" and pat.get("elegibilidade_orcamento")!="NAO_ELEGIVEL":add("CONFORME_ELEGIVEL_ORCAMENTO",[pid])
        if pat.get("constatacao",{}).get("situacao")=="NAO_CONSTATADA" and "inexist" in (pat.get("conclusao_tecnica") or "").lower():add("NAO_CONSTATADA_COMO_INEXISTENTE",[pid])
        if pat.get("causa") and len(set(pat.get("analise_causal",{}).get("fundamentos",[])))<2:add("CAUSA_DERIVADA_DIRETAMENTE_DE_OBS",[pid])
        if any(not isinstance(v,dict) for v in pat.get("consequencias",{}).values()):add("CONSEQUENCIA_LEGACY_NO_PAT_FINAL",[pid])
        reparo=pat.get("recomendacao",{}).get("descricao");campos={"objetivo","sistema","escopo","etapas_gerais","mecanismo_ou_causa_tratada","limitacoes","investigacao_adicional"}
        if pat.get("recomendacao",{}).get("necessaria") and (not isinstance(reparo,dict) or not campos<=set(reparo)):add("REPARO_SEM_CONTEUDO",[pid])
        if pat.get("elegibilidade_orcamento")=="ELEGIVEL_ORCAMENTO_VICIO" and (not isinstance(reparo,dict) or not campos<=set(reparo)):add("ORCAMENTO_SEM_REPARO_REAL",[pid])
        for norma in pat.get("normas_relacionadas",[]):
            refs([norma.get("id")],"NOR",pid)
            if not norma.get("proveniencia"):add("NORMA_SEM_PROVENIENCIA",[pid,str(norma.get("id"))])
            if norma.get("item") and not norma.get("verificada"):add("ITEM_NORMATIVO_NAO_VERIFICADO",[pid,str(norma.get("id"))])
            if norma.get("avaliacao_conformidade",{}).get("resultado") in {"ATENDE","NAO_ATENDE"} and not norma["avaliacao_conformidade"].get("evidencias"):add("NORMA_SOZINHA_PROVA_CONFORMIDADE",[pid,str(norma.get("id"))])
        refs(pat.get("ressalvas_relacionadas",[]),"RES",pid)
    for q in resultado.get("cobertura_quesitos",[]):
        refs([q.get("quesito")],"QUE",q.get("quesito","COBERTURA"));refs(q.get("observacoes",[]),"OBS",q.get("quesito","COBERTURA"))
        for pid in q.get("patologias",[]):
            if pid not in {p["id"] for p in resultado.get("patologias",[])}:add("PAT_INEXISTENTE",[q.get("quesito","COBERTURA"),pid])
        if q.get("status") not in {"MATERIA_JURIDICA","PREJUDICADO"} and not q.get("patologias") and not q.get("observacoes"):add("QUESITO_PERTINENTE_SEM_COBERTURA",[q["quesito"]])
    for qt in resultado.get("questoes_saneadas",[]):
        qid=qt.get("id","QT");refs([qt.get("id")],"QT",qid);refs(qt.get("quesitos",[]),"QUE",qid);refs(qt.get("observacoes",[]),"OBS",qid);refs(qt.get("medicoes",[]),"MED",qid);refs(qt.get("fotografias",[]),"FOT",qid);refs(qt.get("normas",[]),"NOR",qid)
        ligados=[p for p in resultado.get("patologias",[]) if p.get("id") in qt.get("patologias",[])]
        sem_capacidade=any(p.get("analise_causal",{}).get("status_capacidade")=="MOTOR_CAUSAL_NAO_IMPLEMENTADO" for p in ligados)
        if qt.get("status")=="INCONCLUSIVA_POR_LIMITACAO" and sem_capacidade:add("QT_CAUSAL_SEM_CAPACIDADE_DO_MOTOR",[qid,*[p["id"] for p in ligados]])
    usadas={eid for p in resultado.get("patologias",[]) for eid in p.get("evidencias",[])}
    dimensoes_construtivas={"PROJETO_CONSTRUTIVO_DOCUMENTADO","MATERIAL_CONSTRUTIVO_DOCUMENTADO","ESPECIFICACAO_CONSTRUTIVA_DOCUMENTADA","DETALHE_CONSTRUTIVO_DOCUMENTADO","PROCEDIMENTO_EXECUTIVO_DOCUMENTADO","CONTROLE_TECNOLOGICO_DOCUMENTADO","DOCUMENTACAO_OBRA_VERIFICADA"};divergencias_construtivas={"EXECUCAO_DIVERGENTE_DOCUMENTADA","NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA"}
    catalogo_por_id={e.get("id"):e for e in resultado.get("catalogo_evidencias",[])}
    for pat in resultado.get("patologias",[]):
        ligadas=[catalogo_por_id.get(x,{}) for x in pat.get("evidencias",[])];aspectos={a for e in ligadas for a in e.get("aspectos_suportados",[])};fontes={tuple(e.get("proveniencia",[])) or (e.get("id"),) for e in ligadas if set(e.get("aspectos_suportados",[]))&(dimensoes_construtivas|divergencias_construtivas)}
        if pat.get("origem")=="ENDOGENA_CONSTRUTIVA" and not (aspectos&dimensoes_construtivas and aspectos&divergencias_construtivas and len(fontes)>=2):add("ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA",[pat["id"]])
    for e in resultado.get("catalogo_evidencias",[]):
        for a in e.get("auditoria_aspectos",[]):
            if a.get("polaridade")=="NEGADO" and a.get("aspecto") in e.get("aspectos_suportados",[]):add("NEGACAO_CONVERTIDA_EM_FATO",[e["id"],a["aspecto"]])
            if a.get("aspectos_derivados_consultados") is not False:add("ASPECTO_AUTO_GROUNDED",[e["id"],a.get("aspecto","")])
        if e.get("authority") in {"FONTE_PRIMARIA_OFICIAL","FONTE_OFICIAL_VERIFICADA"} and not (e.get("classificacao_fonte")=="FONTE_PRIMARIA_OFICIAL" and e.get("dominio_oficial") is True and e.get("status_verificacao")=="VERIFICADO"):add("AUTORIDADE_NORMATIVA_AUTODECLARADA",[e["id"]])
        negados={a.get("aspecto") for a in e.get("auditoria_aspectos",[]) if a.get("polaridade")=="NEGADO"}
        if e.get("tipo")=="OBSERVACAO" and e.get("resultado")=="OBSERVADO" and negados:add("OBS_NEGADA_COM_RESULTADO_OBSERVADO",[e["id"],*negados])
        normativos={"REQUISITO_NORMATIVO_VERIFICADO","METODO_NORMATIVO_VERIFICADO","CRITERIO_NORMATIVO_VERIFICADO","DEFINICAO_NORMATIVA_VERIFICADA","ESCOPO_NORMATIVO_VERIFICADO","APLICABILIDADE_TEMPORAL"}
        indevidos=set(e.get("aspectos_suportados",[]))-normativos if e.get("tipo")=="NORMA" else set()
        if indevidos:add("NORMA_USADA_COMO_FATO_DO_CASO",[e["id"],*indevidos])
        if e.get("tipo")=="FOTOGRAFIA" and e.get("estado_interpretacao")!="INTERPRETADA" and e.get("aspectos_suportados"):add("FOT_NAO_INTERPRETADA_USADA_COMO_PROVA",[e["id"]])
        if e.get("tipo")=="FOTOGRAFIA" and e.get("descricao")==e.get("finalidade_planejada") and e.get("descricao"):add("FOT_PLANO_USADA_COMO_EVIDENCIA",[e["id"]])
        if e.get("tipo")=="FOTOGRAFIA" and e.get("aspectos_suportados") and any(x in e.get("aspectos_suportados",[]) for x in {"CAUSA","ORIGEM"}):add("ORIGEM_DERIVADA_DIRETAMENTE_DE_FOT",[e["id"]])
        if e.get("tipo")=="NORMA" and "CONFORMIDADE_NORMATIVA" in e.get("aspectos_suportados",[]):add("NORMA_SOZINHA_PROVA_CONFORMIDADE",[e["id"]])
        if e.get("id") in usadas and e.get("tipo") in {"DOCUMENTO","ENSAIO"} and e.get("associacao",{}).get("confianca")=="BAIXA":add(("DOC" if e["tipo"]=="DOCUMENTO" else "ENSAIO")+"_ASSOCIADO_COM_BAIXA_CONFIANCA",[e["id"]])
    for pat in resultado.get("patologias",[]):
        for norma in pat.get("normas_relacionadas",[]):
            if norma.get("authority") in {"FONTE_PRIMARIA_OFICIAL","FONTE_OFICIAL_VERIFICADA"} and not (norma.get("classificacao_fonte")=="FONTE_PRIMARIA_OFICIAL" and norma.get("dominio_oficial") is True and norma.get("status_verificacao")=="VERIFICADO"):add("AUTORIDADE_NORMATIVA_AUTODECLARADA",[pat["id"],str(norma.get("id"))])
    for a in achados:a.pop("chave",None)
    return achados

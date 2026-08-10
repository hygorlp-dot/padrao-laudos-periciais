"""Auditoria claim↔evidence original para o domínio pericial."""
from __future__ import annotations
import re
import unicodedata
TIPOS={"ASPECTO_OBSERVAVEL","FATO_PROCESSUAL","FATO_DOCUMENTAL","CONSTATACAO_DE_VISTORIA","MEDICAO","MANIFESTACAO_TECNICA","MECANISMO","CAUSA","ORIGEM","CRITICIDADE","REQUISITO_NORMATIVO","CONFORMIDADE_NORMATIVA","VICIO_CONSTRUTIVO","REPARABILIDADE","ORCAMENTO","INFERENCIA_TECNICA","LIMITACAO","CONCLUSAO_DE_QT"}
PREFIXOS=("ALG-","DOC-","OBS-","MED-","FOT-","ENS-","NOR-","MOD-","RES-","PAT-","QT-","QUE-","HIP-")
TIPOS_EVIDENCIA={"DOCUMENTO","OBSERVACAO","MEDICAO","FOTOGRAFIA","ENSAIO","NORMA","RESSALVA","MODELO_REFERENCIAL","INFERENCIA_TECNICA"}
def _lista_textual(valor):return isinstance(valor,list) and all(isinstance(x,str) and x.strip() for x in valor)
def _classe_probatoria(e):
    if e.get("classe_probatoria"):return e["classe_probatoria"]
    return "EVIDENCIA_PRIMARIA" if str(e.get("id","")).startswith(("OBS-","MED-","FOT-","DOC-","ENS-","NOR-")) else "INFERENCIA_INTERMEDIARIA"
def _evidencia_valida(e):return isinstance(e,dict) and isinstance(e.get("id"),str) and e["id"].startswith(PREFIXOS) and _classe_probatoria(e)=="EVIDENCIA_PRIMARIA" and _lista_textual(e.get("proveniencia")) and e.get("tipo") in TIPOS_EVIDENCIA and _lista_textual(e.get("aspectos_suportados",[])) and _lista_textual(e.get("aspectos_contraditos",[])) and isinstance(e.get("acessivel",True),bool)
def auditar_claim(claim,evidencias,catalogo=None):
    if claim.get("tipo") not in TIPOS or claim.get("natureza") not in {"FACTUAL","INTERPRETIVE","SYNTHETIC"} or claim.get("saliencia") not in {"LOAD_BEARING","SUPPORTING","ILLUSTRATIVE"} or not isinstance(claim.get("texto"),str) or not claim["texto"].strip() or not isinstance(claim.get("id"),str) or not re.fullmatch(r"CLM-[0-9]{3,}",claim["id"]) or not _lista_textual(claim.get("aspectos_requeridos",[claim.get("tipo")])) or not isinstance(claim.get("detalhe_nao_suportado",False),bool):raise ValueError("contrato da claim inválido")
    if not isinstance(evidencias,list) or catalogo is not None and not isinstance(catalogo,list):raise ValueError("evidências e catálogo devem ser listas")
    catalogo_por_id={e.get("id"):e for e in (catalogo or []) if _evidencia_valida(e)}
    validas=[];incompativel=False
    for relacao in evidencias:
        if not isinstance(relacao,dict):continue
        fonte=catalogo_por_id.get(relacao.get("id"))
        compativel=not (fonte and fonte.get("tipo")=="NORMA" and claim["tipo"] not in {"REQUISITO_NORMATIVO","CONFORMIDADE_NORMATIVA","VIGENCIA","REGULATORIA"})
        if fonte and fonte.get("acessivel",True) and not compativel:incompativel=True
        if fonte and compativel and fonte["tipo"]==relacao.get("tipo") and set(fonte["proveniencia"])==set(relacao.get("proveniencia",[])):validas.append(fonte)
    acessiveis=[e for e in validas if e.get("acessivel",True)];requeridos=set(claim.get("aspectos_requeridos",[claim["tipo"]]));favor=[e for e in acessiveis if requeridos & set(e.get("aspectos_suportados",[]))];contra=[e for e in acessiveis if requeridos & set(e.get("aspectos_contraditos",[]))]
    cobertura=set().union(*(set(e.get("aspectos_suportados",[])) for e in favor)) if favor else set()
    if contra:veredito="CONTRADICTED"
    elif incompativel and not validas:veredito="UNSUBSTANTIATED"
    elif not evidencias or not catalogo or not acessiveis:veredito="UNVERIFIABLE"
    elif claim.get("detalhe_nao_suportado"):veredito="INTERPOLATED"
    elif requeridos and requeridos<=cobertura:veredito="GROUNDED"
    elif favor:veredito="WEAKLY_GROUNDED" if claim.get("saliencia")!="LOAD_BEARING" else "INSUFFICIENT"
    else:veredito="UNSUBSTANTIATED"
    return {"claim_id":claim["id"],"tipo":claim["tipo"],"natureza":claim.get("natureza","INTERPRETIVE"),"saliencia":claim.get("saliencia","SUPPORTING"),"texto":claim["texto"],"evidencias":[e["id"] for e in validas],"veredito":veredito,"auditoria_independente":"NAO","justificativa_resumida":"Veredito obtido da proveniência, acessibilidade e cobertura explícita dos aspectos requeridos.","remediacao":"Manter" if veredito=="GROUNDED" else "Reduzir, ressalvar ou remover a afirmação conforme a evidência disponível."}
def auditar_aspecto(evidencia,aspecto,indice=1):
    claim={"id":f"CLM-{indice:03d}","tipo":"ASPECTO_OBSERVAVEL","natureza":"FACTUAL","saliencia":"SUPPORTING","texto":aspecto,"aspectos_requeridos":[aspecto]}
    return auditar_claim(claim,[evidencia],[evidencia])

def auditar_candidato_aspecto(evidencia,candidato):
    """Audita candidato contra a fonte bruta, sem consultar aspectos derivados."""
    bruto=" ".join(str(evidencia.get(k) or "") for k in ("descricao","resultado","valor","unidade","grandeza","anotacao","requisito","metodo_verificacao","criterio","definicao","escopo","aplicabilidade_temporal"))
    limpar=lambda x:re.sub(r"\s+"," ",unicodedata.normalize("NFKD",str(x)).encode("ascii","ignore").decode().lower()).strip()
    normalizado=limpar(bruto);ancora=limpar(candidato.get("ancora") or "")
    fiel=bool(ancora and ancora in normalizado);polaridade=candidato.get("polaridade","NAO_AVALIADO")
    if not fiel:veredito="UNSUBSTANTIATED"
    elif polaridade=="NEGADO":veredito="CONTRADICTED"
    elif polaridade in {"INCERTO","HIPOTETICO","NAO_AVALIADO"}:veredito="WEAKLY_GROUNDED"
    else:veredito="GROUNDED"
    return {"veredito":veredito,"fidelidade":"ACCURATE" if fiel else "UNSUPPORTED","delta_informacional":"BAIXO" if fiel else "ALTO","fonte_original":bruto,"aspectos_derivados_consultados":False}

def _extrair_claims_legado(resultado):
    claims=[]
    for evidencia in resultado.get("catalogo_evidencias",[]):
        for aspecto in evidencia.get("auditoria_aspectos",[]):
            if aspecto.get("veredito")!="GROUNDED":continue
            claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"ASPECTO_OBSERVAVEL","natureza":"FACTUAL","saliencia":"SUPPORTING","texto":f"ASPECTO_OBSERVAVEL: {aspecto['aspecto']}","evidencia_id":evidencia["id"],"aspectos_requeridos":[aspecto["aspecto"]]})
    for pat in resultado.get("patologias",[]):
        situacao=pat.get("constatacao",{}).get("situacao");base=[("CONSTATACAO_DE_VISTORIA",situacao,"FACTUAL","SUPPORTING"),("MANIFESTACAO_TECNICA",pat.get("manifestacao"),"INTERPRETIVE","SUPPORTING"),("MECANISMO",pat.get("mecanismo"),"INTERPRETIVE","LOAD_BEARING"),("CAUSA",pat.get("causa"),"INTERPRETIVE","LOAD_BEARING"),("ORIGEM",pat.get("origem"),"INTERPRETIVE","LOAD_BEARING"),("CRITICIDADE",pat.get("criticidade"),"INTERPRETIVE","LOAD_BEARING"),("VICIO_CONSTRUTIVO",pat.get("vicio_construtivo",{}).get("caracterizado"),"SYNTHETIC","LOAD_BEARING"),("REPARABILIDADE",pat.get("reparabilidade"),"INTERPRETIVE","SUPPORTING"),("ORCAMENTO",pat.get("elegibilidade_orcamento"),"SYNTHETIC","LOAD_BEARING"),("LIMITACAO","; ".join(pat.get("ressalvas",[])),"FACTUAL","SUPPORTING")]
        for tipo,valor,natureza,saliencia in base:
            if valor not in (None,"",False,"INCONCLUSIVA","NAO_APLICAVEL","PENDENTE"):
                requeridos=[tipo]
                if tipo=="VICIO_CONSTRUTIVO":requeridos=["MANIFESTACAO_TECNICA","CAUSA","ORIGEM"]
                elif tipo=="ORCAMENTO" and valor=="NAO_ELEGIVEL":requeridos=["CONSTATACAO_DE_VISTORIA"]
                claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":tipo,"natureza":natureza,"saliencia":saliencia,"texto":f"{tipo}: {valor}","patologia":pat["id"],"aspectos_requeridos":requeridos})
    for qt in resultado.get("questoes_saneadas",[]):
        if qt.get("conclusao") and qt.get("status")!="PREJUDICADA":claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"CONCLUSAO_DE_QT","natureza":"SYNTHETIC","saliencia":"LOAD_BEARING","texto":qt["conclusao"],"questao":qt["id"],"aspectos_requeridos":["CONSTATACAO_DE_VISTORIA"]})
    for pat in resultado.get("patologias",[]):
        for med in pat.get("medicoes",[]):claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"MEDICAO","natureza":"FACTUAL","saliencia":"SUPPORTING","texto":f"Medição relacionada: {med}","patologia":pat["id"],"aspectos_requeridos":["MEDICAO"]})
        for norma in pat.get("normas_relacionadas",[]):claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"CONFORMIDADE_NORMATIVA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":f"Aplicação normativa: {norma.get('id')}","patologia":pat["id"],"aspectos_requeridos":["CONFORMIDADE_NORMATIVA"]})
        if pat.get("conclusao_tecnica"):
            req=["MANIFESTACAO_TECNICA","CAUSA"] if pat.get("causa") else ["MANIFESTACAO_TECNICA"] if pat.get("constatacao",{}).get("situacao") in {"ANOMALIA","FALHA"} else ["CONSTATACAO_DE_VISTORIA"]
            claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"INFERENCIA_TECNICA","natureza":"SYNTHETIC","saliencia":"LOAD_BEARING","texto":pat["conclusao_tecnica"],"patologia":pat["id"],"aspectos_requeridos":req})
    return claims

# Versão final: separa requisito normativo de comparação e usa aspectos observáveis
# explícitos para claims causais. A redefinição preserva compatibilidade histórica do arquivo.
def extrair_claims(resultado):
    claims=[]
    def add(tipo,valor,natureza,saliencia,pat=None,qt=None,requeridos=None):
        if valor in (None,"",False,"INCONCLUSIVA","NAO_APLICAVEL","PENDENTE"):return
        claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":tipo,"natureza":natureza,"saliencia":saliencia,"texto":f"{tipo}: {valor}",**({"patologia":pat["id"]} if pat else {}),**({"questao":qt["id"]} if qt else {}),"aspectos_requeridos":list(dict.fromkeys(requeridos or [tipo]))})
    for evidencia in resultado.get("catalogo_evidencias",[]):
        for aspecto in evidencia.get("auditoria_aspectos",[]):
            if aspecto.get("veredito")=="GROUNDED":claims.append({"id":f"CLM-{len(claims)+1:03d}","tipo":"ASPECTO_OBSERVAVEL","natureza":"FACTUAL","saliencia":"SUPPORTING","texto":f"ASPECTO_OBSERVAVEL: {aspecto['aspecto']}","evidencia_id":evidencia["id"],"aspectos_requeridos":[aspecto["aspecto"]]})
    for pat in resultado.get("patologias",[]):
        ac=pat.get("analise_causal",{});causais=ac.get("aspectos_requeridos",[]);origem=ac.get("aspectos_origem",[])
        add("CONSTATACAO_DE_VISTORIA",pat.get("constatacao",{}).get("situacao"),"FACTUAL","SUPPORTING",pat,requeridos=["CONSTATACAO_DE_VISTORIA"])
        add("MANIFESTACAO_TECNICA",pat.get("manifestacao"),"INTERPRETIVE","SUPPORTING",pat,requeridos=["CONSTATACAO_DE_VISTORIA"])
        add("MECANISMO",pat.get("mecanismo"),"INTERPRETIVE","LOAD_BEARING",pat,requeridos=causais)
        add("CAUSA",pat.get("causa"),"INTERPRETIVE","LOAD_BEARING",pat,requeridos=causais)
        add("ORIGEM",pat.get("origem"),"INTERPRETIVE","LOAD_BEARING",pat,requeridos=origem)
        req_crit={"CRITICA":["RISCO_SEGURANCA_REGISTRADO"],"MEDIA":["PERDA_FUNCIONAL_REGISTRADA"],"MINIMA":["REPERCUSSAO_LOCALIZADA_REGISTRADA"]}.get(pat.get("criticidade"),[])
        add("CRITICIDADE",pat.get("criticidade"),"INTERPRETIVE","LOAD_BEARING",pat,requeridos=req_crit or ["CONSTATACAO_DE_VISTORIA"])
        if pat.get("vicio_construtivo",{}).get("caracterizado"):add("VICIO_CONSTRUTIVO",True,"SYNTHETIC","LOAD_BEARING",pat,requeridos=["CONSTATACAO_DE_VISTORIA",*causais,*origem])
        if pat.get("elegibilidade_orcamento")!="PENDENTE":add("ORCAMENTO",pat.get("elegibilidade_orcamento"),"SYNTHETIC","LOAD_BEARING",pat,requeridos=[*causais,*origem,"DETALHE_CONSTRUTIVO_DOCUMENTADO"] if pat.get("elegibilidade_orcamento")=="ELEGIVEL_ORCAMENTO_VICIO" else ["CONSTATACAO_DE_VISTORIA"])
        for med in pat.get("medicoes",[]):add("MEDICAO",med,"FACTUAL","SUPPORTING",pat,requeridos=["MEDICAO_REGISTRADA"])
        for norma in pat.get("normas_relacionadas",[]):
            add("REQUISITO_NORMATIVO",norma.get("id"),"FACTUAL","LOAD_BEARING",pat,requeridos=["REQUISITO_NORMATIVO_VERIFICADO"])
            av=norma.get("avaliacao_conformidade",{})
            if av.get("resultado") in {"ATENDE","NAO_ATENDE"}:add("CONFORMIDADE_NORMATIVA",av["resultado"],"SYNTHETIC","LOAD_BEARING",pat,requeridos=["REQUISITO_NORMATIVO_VERIFICADO","MEDICAO_REGISTRADA"])
        req=["CONSTATACAO_DE_VISTORIA",*causais] if pat.get("causa") else ["CONSTATACAO_DE_VISTORIA"]
        add("INFERENCIA_TECNICA",pat.get("conclusao_tecnica"),"SYNTHETIC","LOAD_BEARING",pat,requeridos=req)
    for qt in resultado.get("questoes_saneadas",[]):
        if qt.get("status")!="PREJUDICADA":add("CONCLUSAO_DE_QT",qt.get("conclusao"),"SYNTHETIC","LOAD_BEARING",qt=qt,requeridos=["CONSTATACAO_DE_VISTORIA"])
    return claims

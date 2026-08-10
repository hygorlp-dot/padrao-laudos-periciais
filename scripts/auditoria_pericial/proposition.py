"""Adaptação operacional mínima para proposições normativas e regulatórias."""
from __future__ import annotations

TIPOS={"REQUISITO_NORMATIVO","VIGENCIA","CITACAO","JURIDICA_AUXILIAR","REGULATORIA"}

AUTORIDADES={"FONTE_PRIMARIA_OFICIAL","FONTE_INSTITUCIONAL","NORMA_TECNICA","LITERATURA_CIENTIFICA","REFERENCIA_TECNICA","FONTE_SECUNDARIA","NAO_DETERMINADA"}
def classificar_autoridade(fonte):
    declarada=fonte.get("classificacao_fonte")
    origem=" ".join(map(str,fonte.get("proveniencia",[]))).lower()+" "+str(fonte.get("dominio") or "").lower()
    if declarada=="FONTE_SECUNDARIA" or any(x in origem for x in ("blog","medium.com","wordpress")):return "FONTE_SECUNDARIA"
    identidade=bool(fonte.get("entidade") and (fonte.get("documento") or fonte.get("titulo")) and (fonte.get("url") or fonte.get("dominio")) and fonte.get("proveniencia") and fonte.get("status_verificacao")=="VERIFICADO")
    if declarada=="FONTE_PRIMARIA_OFICIAL" and identidade and fonte.get("dominio_oficial") is True:return "FONTE_PRIMARIA_OFICIAL"
    if declarada in AUTORIDADES-{"FONTE_PRIMARIA_OFICIAL","FONTE_SECUNDARIA","NAO_DETERMINADA"} and identidade:return declarada
    return "NAO_DETERMINADA"

def _fidelidade(claim,fonte):
    conteudo=fonte.get("conteudo_consultado")
    if fonte.get("escopo_fonte")!="CONTEUDO_NORMATIVO" or fonte.get("conteudo_normativo_verificado") is not True or not isinstance(conteudo,str) or not conteudo.strip():return "NAO_AVALIAVEL"
    requisito=str(fonte.get("requisito") or "").strip().lower()
    return "DIRETA" if requisito and requisito in conteudo.lower() else "INSUFICIENTE"

def auditar_proposicoes(claims,grounding,catalogo):
    por_auditoria={a["claim_id"]:a for a in grounding};por_id={e["id"]:e for e in catalogo};resultados=[]
    for claim in claims:
        if claim["tipo"] not in TIPOS:continue
        base=por_auditoria[claim["id"]];fontes=[por_id[x] for x in base.get("evidencias",[]) if x in por_id and por_id[x].get("tipo")=="NORMA"]
        verificadas=[f for f in fontes if f.get("acessivel") and f.get("proveniencia")];avaliadas=[(f,classificar_autoridade(f),_fidelidade(claim,f)) for f in verificadas]
        principal=next((x for x in avaliadas if x[1] in {"FONTE_PRIMARIA_OFICIAL","NORMA_TECNICA"} and x[2]=="DIRETA"),None)
        secundaria=next((x for x in avaliadas if x[1]=="FONTE_SECUNDARIA" and x[2]=="DIRETA"),None)
        veredito="SUPPORTED" if base["veredito"]=="GROUNDED" and principal else "WEAKLY_SUPPORTED" if base["veredito"]=="GROUNDED" and secundaria else "UNVERIFIABLE"
        autoridade=principal[1] if principal else secundaria[1] if secundaria else next((x[1] for x in avaliadas if x[1]!="NAO_DETERMINADA"),"NAO_DETERMINADA")
        resultados.append({"claim_id":claim["id"],"source":[f["id"] for f in verificadas],"verdict":veredito,
                           "authority":autoridade,
                           "source_authority":autoridade,"fidelity":"DIRETA" if principal or secundaria else "NAO_AVALIAVEL",
                           "limitations":[] if veredito=="SUPPORTED" else ["Proposição sem fonte normativa verificável suficiente."],
                           "provenance":sorted({p for f in verificadas for p in f.get("proveniencia",[])})})
    return resultados

"""Orquestra auditorias sem importar ou chamar o motor pericial."""
from __future__ import annotations
from .detector import executar_detector
from .grounding import auditar_claim
from .deep_audit import executar_deep_audit
def executar_auditoria_integrada(resultado,claims_com_evidencias,**fontes):
    rapido=executar_detector(resultado,**fontes)
    grounding=[auditar_claim(item["claim"],item.get("evidencias",[]),item.get("catalogo")) for item in claims_com_evidencias]
    profunda=executar_deep_audit(grounding,resultado)
    materiais=[c for c in grounding if c["saliencia"]=="LOAD_BEARING"]
    if rapido or any(c["veredito"] in {"INTERPOLATED","UNSUBSTANTIATED","INSUFFICIENT","CONTRADICTED"} for c in materiais):gate="BLOQUEADO_PARA_REDACAO"
    elif any(c["veredito"]=="UNVERIFIABLE" for c in materiais):gate="BLOQUEADO_PARA_REDACAO"
    elif any(c["veredito"]=="WEAKLY_GROUNDED" for c in materiais):gate="APTO_PARA_REDACAO_COM_RESSALVAS"
    else:gate="APTO_PARA_REDACAO"
    return {"detector_rapido":rapido,"grounding":grounding,"deep_audit":profunda,"gate":gate,"auditoria_independente":"NAO"}

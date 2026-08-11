"""Migração explícita e fail-closed do plano de vistoria."""
from copy import deepcopy
from scripts.backend_contract.errors import DomainError

VERSAO_ATUAL="2.0.0"

def migrar_plano(dado):
    plano=deepcopy(dado);versao=plano.get("schema_version")
    if versao==VERSAO_ATUAL:return plano
    if versao!="1.0.0":raise DomainError("schema_version futura ou incompatível")
    requisitos=plano.get("requisitos_cobertura")
    if not requisitos:raise DomainError("plano legado sem requisitos_cobertura não pode ser inferido com segurança")
    colecoes={"ATIVIDADE":"atividades","MEDICAO":"medicoes","FOTOGRAFIA":"fotografias","ENSAIO":"ensaios","DOCUMENTO":"documentos_a_solicitar"}
    for r in requisitos:
        r.pop("id",None)
        if not r.get("item_planejado"):
            candidatos=[x.get("id") for x in plano.get(colecoes.get(r.get("tipo"),""),[]) if isinstance(x,dict) and r.get("questao_tecnica") in x.get("questoes_tecnicas",[])]
            if len(candidatos)!=1:raise DomainError("requisito legado sem item_planejado inequivoco")
            r["item_planejado"]=candidatos[0]
    plano["schema_version"]=VERSAO_ATUAL
    return plano

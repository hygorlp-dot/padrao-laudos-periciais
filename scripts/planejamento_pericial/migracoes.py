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
    for i,r in enumerate(requisitos,1):r.setdefault("id",f"REQ-{i:03d}")
    plano["schema_version"]=VERSAO_ATUAL
    return plano

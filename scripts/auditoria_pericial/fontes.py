"""Hierarquia de fontes para auditoria, sem substituir aplicabilidade técnica."""
ORDEM={"FONTE_PRIMARIA_OFICIAL":0,"FONTE_INSTITUCIONAL":1,"NORMA_TECNICA":2,"LITERATURA_CIENTIFICA":3,"REFERENCIA_TECNICA":4,"FONTE_SECUNDARIA":5}
def ordenar_fontes(fontes):return sorted(fontes,key=lambda f:(ORDEM.get(f.get("tipo"),99),f.get("id","")))

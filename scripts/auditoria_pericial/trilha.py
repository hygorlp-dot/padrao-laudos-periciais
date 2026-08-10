"""Gera trilha profissional sem registrar raciocínio oculto."""
from __future__ import annotations
from datetime import datetime,timezone
PROIBIDOS={"chain_of_thought","scratchpad","raciocinio_oculto"}
def _conferir(valor):
    if isinstance(valor,dict):
        if PROIBIDOS & {str(k).lower() for k in valor}:raise ValueError("raciocínio privado não pode integrar a trilha")
        for item in valor.values():_conferir(item)
    elif isinstance(valor,list):
        for item in valor:_conferir(item)
def registrar_trilha(**dados):
    _conferir(dados)
    return {"schema_version":"1.0.0","execucao_id":dados["execucao_id"],"processo":dados.get("processo"),"timestamp":datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),"agente":dados.get("agente","Codex"),"skill":dados.get("skill"),"objetivo":dados.get("objetivo"),"inputs":dados.get("inputs",[]),"fontes":dados.get("fontes",[]),"artefatos":dados.get("artefatos",[]),"decisoes_autonomas":dados.get("decisoes_autonomas",[]),"inferencias":dados.get("inferencias",[]),"pesquisas_online":dados.get("pesquisas_online",[]),"normas_utilizadas":dados.get("normas_utilizadas",[]),"modelos_utilizados":dados.get("modelos_utilizados",[]),"outputs":dados.get("outputs",[]),"auditorias":dados.get("auditorias",[]),"achados":dados.get("achados",[]),"correcoes":dados.get("correcoes",[]),"validacoes_humanas":dados.get("validacoes_humanas",[]),"status":dados.get("status","EM_ANALISE"),"proveniencia":dados.get("proveniencia",[])}

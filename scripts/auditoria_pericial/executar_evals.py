"""Executa cenários declarativos contra o pipeline real de auditoria."""
from __future__ import annotations
import json
from pathlib import Path
try:
    from .deep_audit import executar_deep_audit
    from .grounding import auditar_claim
except ImportError:
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from scripts.auditoria_pericial.deep_audit import executar_deep_audit
    from scripts.auditoria_pericial.grounding import auditar_claim

def _executar_caso(caso):
    entrada=caso["input"];operacao=entrada["operacao"]
    if operacao=="grounding":
        return auditar_claim(entrada["claim"],entrada.get("relacoes",[]),entrada.get("catalogo"))
    if operacao=="deep_audit":
        return {"achados":executar_deep_audit(entrada.get("claims_auditadas",[]),entrada.get("resultado"))}
    raise ValueError(f"operação de eval desconhecida: {operacao}")

def _verificar(obtido,assercoes):
    falhas=[]
    if "veredito_igual" in assercoes and obtido.get("veredito")!=assercoes["veredito_igual"]:falhas.append("veredito_igual")
    tipos={a.get("tipo") for a in obtido.get("achados",[])}
    for tipo in assercoes.get("achado_inclui",[]):
        if tipo not in tipos:falhas.append(f"achado_inclui:{tipo}")
    for tipo in assercoes.get("achado_nao_inclui",[]):
        if tipo in tipos:falhas.append(f"achado_nao_inclui:{tipo}")
    return falhas

def executar(diretorio:Path):
    resultados=[]
    for caminho in sorted(diretorio.glob("*.json")):
        caso=json.loads(caminho.read_text(encoding="utf-8"));obtido=_executar_caso(caso);falhas=_verificar(obtido,caso["assertions"])
        resultados.append({"id":caso["id"],"aprovado":not falhas,"falhas":falhas,"obtido":obtido})
    return resultados

if __name__=="__main__":
    import sys
    raiz=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/"evals/pericial"
    saida=executar(raiz);print(json.dumps(saida,ensure_ascii=False,indent=2));raise SystemExit(0 if all(x["aprovado"] for x in saida) else 1)

"""Valida schema e integridade relacional do plano pré-vistoria."""

from __future__ import annotations
import argparse, json
from pathlib import Path
from jsonschema.validators import validator_for
from jsonschema import FormatChecker
from referencing import Registry, Resource

RAIZ = Path(__file__).resolve().parents[2]
TIPOS_COBERTURA={"ATIVIDADE":"atividades","MEDICAO":"medicoes","FOTOGRAFIA":"fotografias","ENSAIO":"ensaios","DOCUMENTO":"documentos"}

def recalcular_cobertura(dado):
    requisitos=dado.get("requisitos_cobertura",[]);por_quesito={}
    if not requisitos:return {"cobertura":{c["quesito"]:False for c in dado.get("cobertura",[])},"apto":False}
    catalogos={chave:{item.get("id"):set(item.get("questoes_tecnicas",[])) for item in dado.get(chave,[]) if isinstance(item,dict)} for chave in ("atividades","medicoes","fotografias","ensaios")}
    def satisfaz(requisito,ids=None):
        chave=TIPOS_COBERTURA.get(requisito.get("tipo"));qt=requisito.get("questao_tecnica")
        if chave=="documentos":return bool(ids if ids is not None else dado.get("documentos_a_solicitar",[]))
        candidatos=ids if ids is not None else catalogos.get(chave,{})
        return any(item_id in catalogos.get(chave,{}) and qt in catalogos[chave][item_id] for item_id in candidatos) if chave else False
    for c in dado.get("cobertura",[]):
        qts=set(c.get("questoes_tecnicas",[]));ok=bool(qts)
        for requisito in requisitos:
            if requisito.get("obrigatoriedade")!="OBRIGATORIA" or requisito.get("questao_tecnica") not in qts:continue
            chave=TIPOS_COBERTURA.get(requisito.get("tipo"));ok=ok and satisfaz(requisito,c.get(chave,[]) if chave else [])
        por_quesito[c["quesito"]]=ok
    globais=all(satisfaz(r) for r in requisitos if r.get("obrigatoriedade")=="OBRIGATORIA")
    return {"cobertura":por_quesito,"apto":globais and all(por_quesito.values())}

def validar(caminho: Path) -> list[str]:
    schemas = [json.loads(p.read_text(encoding="utf-8")) for p in (RAIZ/"schemas").glob("*.schema.json")]
    registro=Registry()
    for s in schemas: registro=registro.with_resource(s["$id"],Resource.from_contents(s))
    schema=next(s for s in schemas if s["$id"].endswith("plano-vistoria.schema.json")); v=validator_for(schema)(schema,registry=registro,format_checker=FormatChecker())
    dado=json.loads(caminho.read_text(encoding="utf-8")); erros=[e.message for e in v.iter_errors(dado)]
    ids={k:{x["id"] for x in dado[k]} for k in ("atividades","medicoes","fotografias")}
    quesitos=set(dado["quesitos_relacionados"]); calculada=recalcular_cobertura(dado);cobertos={q for q,ok in calculada["cobertura"].items() if ok}
    if quesitos-cobertos: erros.append("Quesitos pertinentes sem cobertura: "+", ".join(sorted(quesitos-cobertos)))
    for c in dado["cobertura"]:
        for chave in ("atividades","medicoes","fotografias"):
            faltam=set(c[chave])-ids[chave]
            if faltam: erros.append(f"Cobertura referencia {chave} inexistentes: {', '.join(faltam)}")
    if dado["status"]!="BLOQUEADO_PARA_VISTORIA" and (erros or not calculada["apto"]): erros.append("Gate não bloqueado apesar de falha relacional ou requisito obrigatório sem cobertura específica")
    return erros

def main():
    p=argparse.ArgumentParser(); p.add_argument("arquivos",nargs="+",type=Path); falhas=0
    for a in p.parse_args().arquivos:
        e=validar(a); print(("APROVADO" if not e else "FALHA")+f": {a}")
        for x in e: print("-",x)
        falhas+=bool(e)
    return int(bool(falhas))
if __name__=="__main__": raise SystemExit(main())

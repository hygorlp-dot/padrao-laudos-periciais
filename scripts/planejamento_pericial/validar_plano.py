"""Valida schema e integridade relacional do plano pré-vistoria."""

from __future__ import annotations
import argparse, json
from pathlib import Path
from jsonschema.validators import validator_for
from jsonschema import FormatChecker
from referencing import Registry, Resource

RAIZ = Path(__file__).resolve().parents[2]

def validar(caminho: Path) -> list[str]:
    schemas = [json.loads(p.read_text(encoding="utf-8")) for p in (RAIZ/"schemas").glob("*.schema.json")]
    registro=Registry()
    for s in schemas: registro=registro.with_resource(s["$id"],Resource.from_contents(s))
    schema=next(s for s in schemas if s["$id"].endswith("plano-vistoria.schema.json")); v=validator_for(schema)(schema,registry=registro,format_checker=FormatChecker())
    dado=json.loads(caminho.read_text(encoding="utf-8")); erros=[e.message for e in v.iter_errors(dado)]
    ids={k:{x["id"] for x in dado[k]} for k in ("atividades","medicoes","fotografias")}
    quesitos=set(dado["quesitos_relacionados"]); cobertos={c["quesito"] for c in dado["cobertura"] if c["planejada"]}
    if quesitos-cobertos: erros.append("Quesitos pertinentes sem cobertura: "+", ".join(sorted(quesitos-cobertos)))
    for c in dado["cobertura"]:
        for chave in ("atividades","medicoes","fotografias"):
            faltam=set(c[chave])-ids[chave]
            if faltam: erros.append(f"Cobertura referencia {chave} inexistentes: {', '.join(faltam)}")
    if dado["status"]!="BLOQUEADO_PARA_VISTORIA" and erros: erros.append("Gate não bloqueado apesar de falha relacional")
    return erros

def main():
    p=argparse.ArgumentParser(); p.add_argument("arquivos",nargs="+",type=Path); falhas=0
    for a in p.parse_args().arquivos:
        e=validar(a); print(("APROVADO" if not e else "FALHA")+f": {a}")
        for x in e: print("-",x)
        falhas+=bool(e)
    return int(bool(falhas))
if __name__=="__main__": raise SystemExit(main())

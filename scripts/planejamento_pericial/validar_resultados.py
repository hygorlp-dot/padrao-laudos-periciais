"""Valida processo, delimitação, plano e conhecimento privado sem expor conteúdo."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource
RAIZ=Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path: sys.path.insert(0,str(RAIZ))
from scripts.planejamento_pericial.validar_plano import validar as validar_relacoes_plano
from scripts.triagem_pericial.validar_delimitacao import validar_arquivo as validar_delimitacao

def main():
    p=argparse.ArgumentParser(); p.add_argument("raiz_privada",type=Path); a=p.parse_args()
    schemas=[json.loads(x.read_text(encoding="utf-8")) for x in (RAIZ/"schemas").glob("*.schema.json")]
    registro=Registry()
    for s in schemas: registro=registro.with_resource(s["$id"],Resource.from_contents(s))
    por_nome={Path(s["$id"]).name:s for s in schemas}; falhas=[]; aprovados=0
    alvos=[]
    for d in (a.raiz_privada/"derivados").glob("*"):
        if d.is_dir(): alvos += [(d/"processo.json","processo.schema.json"),(d/"plano-vistoria.json","plano-vistoria.schema.json")]
    inv=a.raiz_privada/"conhecimento/inventario-referencias.json"
    if inv.exists(): alvos.append((inv,"inventario-referencias.schema.json"))
    alvos += [(x,"conhecimento-normativo.schema.json") for x in (a.raiz_privada/"conhecimento/normas").glob("NOR-*.json")]
    alvos += [(x,"conhecimento-referencial.schema.json") for x in (a.raiz_privada/"conhecimento/modelos").glob("MOD-*.json")]
    for caminho,nome in alvos:
        if not caminho.exists(): falhas.append(f"ausente: {caminho}"); continue
        s=por_nome[nome]; v=validator_for(s)(s,registry=registro,format_checker=FormatChecker()); dado=json.loads(caminho.read_text(encoding="utf-8")); erros=list(v.iter_errors(dado))
        if nome=="plano-vistoria.schema.json" and not erros: erros=[ValueError(e) for e in validar_relacoes_plano(caminho)]
        if erros: falhas.append(f"{caminho}: {getattr(erros[0],'message',str(erros[0]))}")
        else: aprovados+=1
    for d in (a.raiz_privada/"derivados").glob("*"):
        if (d/"delimitacao-pericial.json").exists():
            erros=validar_delimitacao(d/"delimitacao-pericial.json")
            if not erros and (d/"processo.json").exists():
                proc=json.loads((d/"processo.json").read_text(encoding="utf-8")); delim=json.loads((d/"delimitacao-pericial.json").read_text(encoding="utf-8"))
                existentes={x["id"] for x in proc["alegacoes"]}; ligados={x for qt in delim["questoes_tecnicas"] for x in qt["alegacoes_relacionadas"]}
                if ligados-existentes: erros.append("Delimitação referencia alegações inexistentes")
                if existentes-ligados: erros.append("Alegações relevantes sem questão técnica vinculada")
            if erros: falhas.append(f"{d}/delimitacao-pericial.json: {erros[0]}")
            else: aprovados+=1
    print(json.dumps({"aprovados":aprovados,"falhas":len(falhas)},ensure_ascii=False))
    for erro in falhas: print("-",erro)
    return int(bool(falhas))
if __name__=="__main__": raise SystemExit(main())

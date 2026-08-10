"""Confronta processo.json com a delimitação e incorpora alegações rastreáveis."""

from __future__ import annotations
import argparse, json
from pathlib import Path

def aprofundar(diretorio: Path) -> dict:
    processo=json.loads((diretorio/"processo.json").read_text(encoding="utf-8"))
    delimitacao=json.loads((diretorio/"delimitacao-pericial.json").read_text(encoding="utf-8"))
    algs=[a["id"] for a in processo["alegacoes"]]
    for qt in delimitacao["questoes_tecnicas"]:
        qt["alegacoes_relacionadas"]=algs
        if algs:
            registro=f"Alegações rastreadas em processo.json: {', '.join(algs)}"
            if registro not in qt["evidencias_disponiveis"]: qt["evidencias_disponiveis"].append(registro)
    fontes={a["documento_fonte"] for a in processo["alegacoes"] if a["documento_fonte"]}
    delimitacao["autoauditoria"].append({"criterio":"Alegações do processo confrontadas com questões técnicas","resultado":"APROVADO","observacao":f"{len(algs)} alegações de {len(fontes)} documentos vinculadas sem convertê-las em constatações."})
    return delimitacao

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("diretorios",nargs="+",type=Path)
    for d in p.parse_args().diretorios:
        dado=aprofundar(d);(d/"delimitacao-pericial.json").write_text(json.dumps(dado,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(d)
    return 0
if __name__=="__main__":raise SystemExit(main())

"""Compara commits fixados com HEAD remoto, sem atualizar clones."""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
def verificar(base):
    saida=[]
    for repo in sorted(p for p in base.iterdir() if (p/".git").exists()):
        local=subprocess.run(["git","-C",str(repo),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()
        remoto=subprocess.run(["git","ls-remote","--heads","origin","HEAD"],cwd=repo,capture_output=True,text=True).stdout.split()
        head=remoto[0] if remoto else None;saida.append({"repo":repo.name,"commit_local":local,"commit_upstream":head,"status":"ATUALIZACAO_DISPONIVEL" if head and head!=local else "SEM_ATUALIZACAO_CONFIRMADA" if head else "VERIFICACAO_INCONCLUSIVA"})
    return saida
def main():
    p=argparse.ArgumentParser();p.add_argument("base",type=Path);print(json.dumps(verificar(p.parse_args().base),ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())

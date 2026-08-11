"""Compara o commit local ao tip real da branch upstream, sem modificar clones."""
from __future__ import annotations
import argparse,json,subprocess
from pathlib import Path
def _git(repo,*args,check=False):return subprocess.run(["git","-C",str(repo),*args],capture_output=True,text=True,check=check)
def verificar(base):
    saida=[]
    for repo in sorted(p for p in base.iterdir() if (p/".git").exists()):
        local=_git(repo,"rev-parse","HEAD",check=True).stdout.strip();branch=_git(repo,"branch","--show-current").stdout.strip()
        if not branch:saida.append({"repo":repo.name,"commit_local":local,"commit_upstream":None,"branch_upstream":None,"status":"VERIFICACAO_INCONCLUSIVA"});continue
        remoto=subprocess.run(["git","ls-remote","--heads","origin",f"refs/heads/{branch}"],cwd=repo,capture_output=True,text=True)
        partes=remoto.stdout.split();head=partes[0] if remoto.returncode==0 and partes else None
        saida.append({"repo":repo.name,"commit_local":local,"commit_upstream":head,"branch_upstream":branch,"status":"ATUALIZACAO_DISPONIVEL" if head and head!=local else "SEM_ATUALIZACAO_CONFIRMADA" if head==local else "VERIFICACAO_INCONCLUSIVA"})
    return saida
def main():
    p=argparse.ArgumentParser();p.add_argument("base",type=Path);print(json.dumps(verificar(p.parse_args().base),ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())

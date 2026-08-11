"""Cataloga clones externos privados sem executar código proveniente deles."""
from __future__ import annotations
import argparse,hashlib,json,re,subprocess
from datetime import datetime,timezone
from pathlib import Path

REPOS={"impeccable":"https://github.com/pbakaus/impeccable.git","claim-audit":"https://github.com/mhalle/claim-audit.git","awesome-legal-skills":"https://github.com/lawve-ai/awesome-legal-skills.git"}
REVIEWS_APROVADOS={
 "impeccable":{"review_status":"APPROVED_WITH_RESTRICTIONS","review_evidence":"docs/terceiros/integracoes-agentes.md","commit_pin":"2ab054d1f400c5ec085133352232ffc2617f0d54","license":"Apache-2.0","restrictions":["frontend only","no private data"]},
 "claim-audit":{"review_status":"APPROVED_LOCAL","review_evidence":"docs/terceiros/integracoes-agentes.md","commit_pin":"f09c72ef22119692667dce2b288fc51a24534db5","license":"MIT","restrictions":["local only"]},
 "awesome-legal-skills":{"review_status":"REFERENCE_ONLY","review_evidence":"docs/terceiros/integracoes-agentes.md","commit_pin":"4b0a895640d44add67ab4db1a0250e5a48888ee1","license":"CC-BY-NC-ND-4.0","restrictions":["no automatic execution"]},
}
def politica_trust(_nome,review):
    if not review:return {"review_status":"UNREVIEWED","review_evidence":None,"commit_pin":None,"license":None,"restrictions":["FAIL_CLOSED"]}
    obrigatorios=("review_status","review_evidence","commit_pin","license","restrictions")
    return dict(review) if all(review.get(k) for k in obrigatorios) else {"review_status":"UNREVIEWED","review_evidence":None,"commit_pin":None,"license":None,"restrictions":["FAIL_CLOSED"]}
SINAIS_EGRESS=(r"https?://",r"\brequests\b",r"\bhttpx\b",r"\burllib\b",r"\bfetch\s*\(",r"\bcurl\b",r"\bwget\b",r"\bsocket\b",r"webhook",r"telemetr",r"upload",r"download",r"api[_ -]?key",r"token")
def classificar_egress(textos,ausencia_verificada=False):
    conteudo="\n".join(map(str,textos)).lower()
    if any(re.search(p,conteudo,re.I) for p in SINAIS_EGRESS):return "YES"
    return "NO_VERIFIED" if ausencia_verificada else "UNKNOWN"
def pode_receber_dados_privados(egress_status,trust):
    """Fail-closed: terceiros nunca recebem dados privados por inferência heurística."""
    return bool(
        egress_status == "NO_VERIFIED"
        and trust.get("review_status") in {"APPROVED_LOCAL", "APPROVED_WITH_RESTRICTIONS"}
        and "no private data" not in trust.get("restrictions", [])
        and "FAIL_CLOSED" not in trust.get("restrictions", [])
    )
def _git(repo,*args):return subprocess.run(["git","-C",str(repo),*args],capture_output=True,text=True,check=True).stdout.strip()
def _licenca(path):
    texto=path.read_text(encoding="utf-8",errors="replace") if path.exists() else ""
    baixo=texto.lower()
    if "apache license" in baixo:return "Apache-2.0"
    if "mit license" in baixo:return "MIT"
    if "attribution-noncommercial-noderivatives" in baixo:return "CC-BY-NC-ND-4.0"
    if "gnu affero" in baixo:return "AGPL"
    if "gnu general public" in baixo:return "GPL"
    return "NAO_IDENTIFICADA"
def _frontmatter(path):
    texto=path.read_text(encoding="utf-8",errors="replace");bloco=texto.split("---",2)[1] if texto.startswith("---") and texto.count("---")>=2 else ""
    return {k:m.group(1).strip().strip('"\'') for k in ("name","description","author","license","version","category") if (m:=re.search(rf"(?im)^{k}:\s*(.+)$",bloco))}
def catalogar(base:Path,destino:Path):
    destino.mkdir(parents=True,exist_ok=True);agora=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds");relatorios=[]
    for indice,(nome,url) in enumerate(REPOS.items(),1):
        repo=base/nome;arquivos=[p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts];licenca=_licenca(repo/"LICENSE")
        executaveis=[p.relative_to(repo).as_posix() for p in arquivos if p.suffix.lower() in {".sh",".ps1",".js",".mjs",".cjs",".py"}]
        instalacao=[p.relative_to(repo).as_posix() for p in arquivos if p.name.lower() in {"package.json","package-lock.json","requirements.txt","pyproject.toml","setup.py"}]
        risco="RISCO_MEDIO" if executaveis or instalacao else "RISCO_BAIXO"
        textos=[p.read_text(encoding="utf-8",errors="ignore") for p in arquivos if p.suffix.lower() in {".md",".py",".js",".mjs",".cjs",".sh",".ps1"}]
        obj={"id":f"REP-EXT-{indice:03d}","nome":nome,"url":url,"commit":_git(repo,"rev-parse","HEAD"),"branch":_git(repo,"branch","--show-current"),"consultado_em":agora,"licenca_raiz":licenca,"arquivos":len(arquivos),"tamanho_bytes":sum(p.stat().st_size for p in arquivos),"skills":len(list(repo.rglob("SKILL.md"))),"arquivos_instalacao":instalacao,"scripts_executaveis":executaveis,"hooks":[p.relative_to(repo).as_posix() for p in arquivos if "hook" in p.name.lower()],"risco":risco,"justificativa":"Execução externa não autorizada; integração apenas após inspeção e seleção manual.","trust":politica_trust(nome,REVIEWS_APROVADOS.get(nome)),"external_data_egress_required":classificar_egress(textos)}
        (destino/f"REP-EXT-{indice:03d}.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");relatorios.append(obj)
    awesome=base/"awesome-legal-skills";catalogo=[]
    for skill in sorted((awesome/"skills").glob("*/SKILL.md")):
        meta=_frontmatter(skill);pasta=skill.parent;licenca=meta.get("license") or _licenca(pasta/"LICENSE")
        arquivos=[p for p in pasta.rglob("*") if p.is_file()]
        textos=[p.read_text(encoding="utf-8",errors="ignore") for p in arquivos if p.suffix.lower() in {".md",".py",".js",".mjs",".cjs",".sh",".ps1"}]
        catalogo.append({"name":meta.get("name",pasta.name),"author":meta.get("author"),"license":licenca,"version":meta.get("version"),"description":meta.get("description"),"categoria":meta.get("category"),"path":pasta.relative_to(awesome).as_posix(),"scripts":[p.relative_to(pasta).as_posix() for p in arquivos if "scripts" in p.parts],"dependencies":[p.name for p in arquivos if p.name in {"requirements.txt","package.json","pyproject.toml"}],"evals":any("eval" in p.parts for p in arquivos),"external_data_egress_required":classificar_egress(textos),"trust":politica_trust(meta.get("name",pasta.name),None)})
    (destino/"catalogo-awesome-legal-skills.json").write_text(json.dumps({"gerado_em":agora,"commit":relatorios[2]["commit"],"skills":catalogo},ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    return relatorios,catalogo
def main():
    p=argparse.ArgumentParser();p.add_argument("base",type=Path);p.add_argument("destino",type=Path);a=p.parse_args();r,c=catalogar(a.base,a.destino);print(json.dumps({"repositorios":len(r),"skills":len(c)},ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())

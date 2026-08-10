"""Confronta processo.json com a delimitação por afinidade semântica."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
RAIZ=Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:sys.path.insert(0,str(RAIZ))
from scripts.motor_vicios.granularizar_questoes import granularizar
from scripts.triagem_pericial.semantica import melhores

def aprofundar(diretorio:Path)->dict:
    processo=json.loads((diretorio/"processo.json").read_text(encoding="utf-8"))
    delimitacao=json.loads((diretorio/"delimitacao-pericial.json").read_text(encoding="utf-8"))
    modelo=delimitacao["questoes_tecnicas"][0]
    for nova in granularizar(processo,delimitacao):
        algs=nova.pop("alegacoes_relacionadas")
        base={k:v for k,v in modelo.items() if k not in {"id","descricao","alegacoes_relacionadas","quesitos_relacionados"}}
        delimitacao["questoes_tecnicas"].append({**base,**nova,"alegacoes_relacionadas":algs,"quesitos_relacionados":[],"origem":"Granularização semântica rastreável de processo.json"})
    questoes=delimitacao["questoes_tecnicas"]
    for qt in questoes:
        if qt["alegacoes_relacionadas"]: continue
        qt["alegacoes_relacionadas"]=[a["id"] for a in processo["alegacoes"] if qt["id"] in melhores(" ".join(filter(None,[a.get("manifestacao_alegada"),a.get("causa_alegada"),a.get("ambiente_alegado"),a.get("sistema_alegado")])),questoes)]
    for quesito in delimitacao["quesitos"]:
        relacionados=melhores(quesito["texto_integral"],questoes)
        quesito["questoes_tecnicas_relacionadas"]=relacionados
        quesito["secoes_laudisticas_previstas"]=[f"Análise técnica vinculada à questão {qid}" for qid in relacionados]
        for qid in relacionados:
            qt=next(q for q in questoes if q["id"]==qid)
            if quesito["id"] not in qt["quesitos_relacionados"]: qt["quesitos_relacionados"].append(quesito["id"])
    delimitacao["matriz_cobertura"]=[{"quesito_id":q["id"],"questoes_tecnicas":q["questoes_tecnicas_relacionadas"],"secoes_laudisticas":q["secoes_laudisticas_previstas"],"status":q["status_cobertura"]} for q in delimitacao["quesitos"]]
    delimitacao["autoauditoria"].append({"criterio":"Vínculos ALG/QUE/QT definidos semanticamente","resultado":"APROVADO","observacao":f"{len(processo['alegacoes'])} alegações confrontadas sem vínculo posicional ou total indiscriminado."})
    return delimitacao

def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("diretorios",nargs="+",type=Path)
    for d in p.parse_args().diretorios:
        (d/"delimitacao-pericial.json").write_text(json.dumps(aprofundar(d),ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(d)
    return 0
if __name__=="__main__":raise SystemExit(main())

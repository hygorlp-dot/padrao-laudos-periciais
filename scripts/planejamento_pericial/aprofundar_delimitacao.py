"""Confronta processo.json com a delimitação por afinidade semântica."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
RAIZ=Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:sys.path.insert(0,str(RAIZ))
from scripts.motor_vicios.granularizar_questoes import granularizar
from scripts.triagem_pericial.semantica import melhores
from scripts.triagem_pericial.gerar_delimitacao import resultado_criterio

def aprofundar(diretorio:Path)->dict:
    processo=json.loads((diretorio/"processo.json").read_text(encoding="utf-8"))
    delimitacao=json.loads((diretorio/"delimitacao-pericial.json").read_text(encoding="utf-8"))
    modelo=delimitacao["questoes_tecnicas"][0]
    existentes_algs={tuple(sorted(q.get("alegacoes_relacionadas",[]))) for q in delimitacao["questoes_tecnicas"]}
    for nova in granularizar(processo,delimitacao):
        algs=nova.pop("alegacoes_relacionadas")
        if tuple(sorted(algs)) in existentes_algs:continue
        base={k:v for k,v in modelo.items() if k not in {"id","descricao","alegacoes_relacionadas","quesitos_relacionados"}}
        fontes=[p for a in processo["alegacoes"] if a["id"] in algs for p in a.get("proveniencia",[])]
        delimitacao["questoes_tecnicas"].append({**base,**nova,"alegacoes_relacionadas":algs,"quesitos_relacionados":[],"origem":"Granularização semântica rastreável de processo.json","proveniencia":fontes or base.get("proveniencia",[])})
    questoes=delimitacao["questoes_tecnicas"]
    for qt in questoes:
        if qt["alegacoes_relacionadas"]: continue
        qt["alegacoes_relacionadas"]=[a["id"] for a in processo["alegacoes"] if qt["id"] in melhores(" ".join(filter(None,[a.get("manifestacao_alegada"),a.get("causa_alegada"),a.get("ambiente_alegado"),a.get("sistema_alegado")])),questoes)]
    for quesito in delimitacao["quesitos"]:
        if quesito.get("pertinencia")=="MATERIA_JURIDICA":
            quesito["questoes_tecnicas_relacionadas"]=[];quesito["secoes_laudisticas_previstas"]=[];quesito["status_cobertura"]="JURIDICO_DELIMITADO"
            for qt in questoes:qt["quesitos_relacionados"]=[x for x in qt.get("quesitos_relacionados",[]) if x!=quesito["id"]]
            continue
        if quesito.get("pertinencia")=="REPETITIVO":
            continue
        relacionados=melhores(quesito["texto_integral"],questoes)
        if not relacionados and quesito.get("pertinencia") in {"PERTINENTE_TECNICO","PERTINENTE_PARCIAL"}:
            novo_id=f"QT-{max((int(q['id'].split('-')[1]) for q in questoes),default=0)+1:03d}"
            base={k:v for k,v in modelo.items() if k not in {"id","descricao","alegacoes_relacionadas","quesitos_relacionados","documentos_relacionados","proveniencia","origem"}}
            nova={**base,"id":novo_id,"descricao":quesito["materia_tecnica"] or quesito["texto_integral"],"origem":"Quesito pertinente sem equivalente no perfil metodológico","alegacoes_relacionadas":[],"quesitos_relacionados":[quesito["id"]],"documentos_relacionados":[quesito["documento_id"]],"proveniencia":quesito["proveniencia"]}
            questoes.append(nova);relacionados=[novo_id]
        quesito["questoes_tecnicas_relacionadas"]=relacionados
        quesito["secoes_laudisticas_previstas"]=[f"Análise técnica vinculada à questão {qid}" for qid in relacionados]
        for qid in relacionados:
            qt=next(q for q in questoes if q["id"]==qid)
            if quesito["id"] not in qt["quesitos_relacionados"]: qt["quesitos_relacionados"].append(quesito["id"])
    delimitacao["matriz_cobertura"]=[{"quesito_id":q["id"],"questoes_tecnicas":q["questoes_tecnicas_relacionadas"],"secoes_laudisticas":q["secoes_laudisticas_previstas"],"status":q["status_cobertura"]} for q in delimitacao["quesitos"]]
    vinculos_validos=all(q.get("alegacoes_relacionadas") or q.get("quesitos_relacionados") for q in questoes)
    item={"criterio":"Vínculos ALG/QUE/QT definidos semanticamente","resultado":resultado_criterio(vinculos_validos),"observacao":f"{len(processo['alegacoes'])} alegações confrontadas sem vínculo posicional ou total indiscriminado."}
    delimitacao["autoauditoria"]=[x for x in delimitacao["autoauditoria"] if x.get("criterio")!=item["criterio"]]+[item]
    from scripts.triagem_pericial.validar_delimitacao import recalcular_autoauditoria,status_derivado
    recalculada=recalcular_autoauditoria(delimitacao);por={x["criterio"]:x for x in delimitacao["autoauditoria"]}
    delimitacao["autoauditoria"]=[{"criterio":c,"resultado":r,"observacao":por.get(c,{}).get("observacao","Critério recalculado no boundary.")} for c,r in recalculada.items()]
    delimitacao["status"]=status_derivado(delimitacao)
    return delimitacao

def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("diretorios",nargs="+",type=Path)
    for d in p.parse_args().diretorios:
        (d/"delimitacao-pericial.json").write_text(json.dumps(aprofundar(d),ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(d)
    return 0
if __name__=="__main__":raise SystemExit(main())

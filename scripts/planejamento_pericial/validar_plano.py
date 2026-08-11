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
    catalogos["documentos"]={item.get("id"):set(item.get("questoes_tecnicas",[])) for item in dado.get("documentos_a_solicitar",[]) if isinstance(item,dict)}
    def satisfaz(requisito,ids=None):
        chave=TIPOS_COBERTURA.get(requisito.get("tipo"));qt=requisito.get("questao_tecnica")
        candidatos=ids if ids is not None else catalogos.get(chave,{})
        esperado=requisito.get("item_planejado")
        return any(item_id in catalogos.get(chave,{}) and qt in catalogos[chave][item_id] and (not esperado or item_id==esperado) for item_id in candidatos) if chave else False
    for c in dado.get("cobertura",[]):
        qts=set(c.get("questoes_tecnicas",[]));ok=bool(qts)
        for requisito in requisitos:
            if requisito.get("obrigatoriedade")!="OBRIGATORIA" or requisito.get("questao_tecnica") not in qts:continue
            chave=TIPOS_COBERTURA.get(requisito.get("tipo"));ok=ok and satisfaz(requisito,c.get(chave,[]) if chave else [])
        por_quesito[c["quesito"]]=ok
    globais=all(satisfaz(r) for r in requisitos if r.get("obrigatoriedade")=="OBRIGATORIA")
    return {"cobertura":por_quesito,"apto":globais and all(por_quesito.values())}

def recalcular_execucao(plano,vistoria):
    """Recalcula REQUIRED→EXECUTED sem confiar no status persistido."""
    cobertura={c.get("planejado"):c for c in vistoria.get("cobertura",[]) if c.get("planejado")}
    catalogos={"ATIVIDADE":{x.get("id"):x for x in vistoria.get("atividades_executadas",[])},"FOTOGRAFIA":{x.get("id"):x for x in vistoria.get("fotografias",[])},"MEDICAO":{x.get("id"):x for x in vistoria.get("medicoes",[])},"ENSAIO":{x.get("id"):x for x in vistoria.get("ensaios",[])},"DOCUMENTO":{x.get("id"):x for x in vistoria.get("documentos_obtidos",[])}}
    campos_plano={"ATIVIDADE":"atividade_planejada","FOTOGRAFIA":"fotografia_planejada","MEDICAO":"medicao_planejada","ENSAIO":"ensaio_planejado","DOCUMENTO":"documento_planejado"}
    planejados={tipo:{x.get("id"):x for x in plano.get(chave,[]) if isinstance(x,dict)} for tipo,chave in TIPOS_COBERTURA.items()}
    faltantes=[]
    for requisito in plano.get("requisitos_cobertura",[]):
        if requisito.get("obrigatoriedade")!="OBRIGATORIA":continue
        planejado=requisito.get("item_planejado");tipo=requisito.get("tipo");qt=requisito.get("questao_tecnica")
        item_plano=planejados.get(tipo,{}).get(planejado)
        if not item_plano or qt not in item_plano.get("questoes_tecnicas",[]):
            faltantes.append({"questao_tecnica":qt,"tipo":tipo,"item_planejado":planejado});continue
        candidatos=[planejado] if planejado else [c.get("planejado") for c in vistoria.get("cobertura",[]) if c.get("tipo")==requisito.get("tipo")]
        satisfeito=False
        for item in candidatos:
            execucao=cobertura.get(item,{})
            artefatos=[catalogos.get(tipo,{}).get(i) for i in execucao.get("executado",[])]
            direto=execucao.get("status")=="EXECUTADO" and any(a and a.get(campos_plano[tipo])==planejado and qt in a.get("questoes",a.get("questoes_tecnicas",[])) for a in artefatos)
            equivalentes=set(execucao.get("evidencia_equivalente",[]));meta=execucao.get("equivalencia") or {};todos=[(t,x) for t,cat in catalogos.items() for x in cat.values()]
            equivalentes_validos=[e for t,e in todos if t==tipo and e.get("id") in equivalentes and qt in e.get("questoes",e.get("questoes_tecnicas",[]))]
            capability_esperada=requisito.get("capability") or tipo
            equivalente=(execucao.get("status")=="SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE" and bool(equivalentes_validos) and
                         meta.get("requisito_original")==planejado and meta.get("tipo_evidencia")==tipo and meta.get("capability")==capability_esperada and
                         bool(meta.get("metodo_substituto")) and bool(execucao.get("justificativa_equivalencia")))
            satisfeito=satisfeito or direto or equivalente
        if not satisfeito:faltantes.append({"questao_tecnica":requisito.get("questao_tecnica"),"tipo":requisito.get("tipo"),"item_planejado":planejado})
    return {"apto":bool(plano.get("requisitos_cobertura")) and not faltantes,"faltantes":faltantes}

def validar(caminho: Path) -> list[str]:
    schemas = [json.loads(p.read_text(encoding="utf-8")) for p in (RAIZ/"schemas").glob("*.schema.json")]
    registro=Registry()
    for s in schemas: registro=registro.with_resource(s["$id"],Resource.from_contents(s))
    schema=next(s for s in schemas if s["$id"].endswith("plano-vistoria.schema.json")); v=validator_for(schema)(schema,registry=registro,format_checker=FormatChecker())
    try:dado=json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError,UnicodeDecodeError,OSError) as exc:return [f"JSON inválido ou ilegível: {type(exc).__name__}"]
    from scripts.planejamento_pericial.migracoes import migrar_plano
    from scripts.backend_contract.errors import DomainError
    try:
        dado=migrar_plano(dado)
    except DomainError as exc:return [f"Migração/versão inválida: {exc}"]
    erros=[e.message for e in v.iter_errors(dado)]
    if erros:return erros
    ids={k:{x["id"] for x in dado.get(k,[]) if isinstance(x,dict) and x.get("id")} for k in ("atividades","medicoes","fotografias")}
    quesitos=set(dado.get("quesitos_relacionados",[])); calculada=recalcular_cobertura(dado);cobertos={q for q,ok in calculada["cobertura"].items() if ok}
    if quesitos-cobertos: erros.append("Quesitos pertinentes sem cobertura: "+", ".join(sorted(quesitos-cobertos)))
    for c in dado.get("cobertura",[]):
        for chave in ("atividades","medicoes","fotografias"):
            faltam=set(c.get(chave,[]))-ids[chave]
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

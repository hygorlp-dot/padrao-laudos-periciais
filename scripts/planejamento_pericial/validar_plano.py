"""Valida schema e integridade relacional do plano pré-vistoria."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from decimal import Decimal,InvalidOperation
import re
import unicodedata
from jsonschema.validators import validator_for
from jsonschema import FormatChecker
from referencing import Registry, Resource

RAIZ = Path(__file__).resolve().parents[2]
TIPOS_COBERTURA={"ATIVIDADE":"atividades","MEDICAO":"medicoes","FOTOGRAFIA":"fotografias","ENSAIO":"ensaios","DOCUMENTO":"documentos"}
CATALOGOS_PLANEJADOS={**TIPOS_COBERTURA,"DOCUMENTO":"documentos_a_solicitar"}
TIPOS_EQUIVALENCIA_SUPORTADOS=frozenset({"MEDICAO","FOTOGRAFIA"})

def _normalizar_semantica(valor):
    base=unicodedata.normalize("NFKD",str(valor or "")).encode("ascii","ignore").decode().casefold()
    return re.sub(r"\s+"," ",base).strip()

def _unidade_planejada(item):
    texto=" ".join(str(item.get(c) or "") for c in ("grandeza","criterio","precisao_necessaria"))
    unidades=re.findall(r"(?i)(?<![a-z])(?:mm|cm|m|%|°c|kpa|mpa|pa)(?![a-z])",texto)
    return unidades[-1].casefold() if unidades else None

def _grandeza_compativel(planejada,executada):
    a,b=_normalizar_semantica(planejada),_normalizar_semantica(executada)
    categorias={"ABERTURA":("abertura","fissura","trinca"),"UMIDADE":("umidade","teor higrometrico"),"TEMPERATURA":("temperatura",),"PRESSAO":("pressao",)}
    def categoria(texto):return next((nome for nome,termos in categorias.items() if any(t in texto for t in termos)),texto)
    return bool(a and b and categoria(a)==categoria(b))

def _medicao_equivalente(item_plano,evidencia,qt):
    try:
        valor=Decimal(str(evidencia.get("valor")))
        if not valor.is_finite():return False
    except (InvalidOperation,ValueError,TypeError):return False
    unidade_esperada=_unidade_planejada(item_plano);unidade_obtida=str(evidencia.get("unidade") or "").strip().casefold()
    local_esperado=_normalizar_semantica(item_plano.get("local"));local_obtido=_normalizar_semantica(evidencia.get("local"))
    return bool(_grandeza_compativel(item_plano.get("grandeza"),evidencia.get("grandeza")) and unidade_esperada and unidade_obtida==unidade_esperada and
                (not local_esperado or local_obtido==local_esperado) and qt in evidencia.get("questoes",evidencia.get("questoes_tecnicas",[])) and
                evidencia.get("observacoes") and str(evidencia.get("metodo") or "").strip())

def capability_item(tipo,item):
    campos={"MEDICAO":("grandeza",),"FOTOGRAFIA":("finalidade","finalidade_planejada")}.get(tipo,())
    valores=[str(item.get(c) or "").strip().casefold() for c in campos if item.get(c)]
    return " | ".join(valores) if valores else None

_STATUS_NAO_COBRIVEL=frozenset({"EXTRACAO_INDETERMINADA","NAO_MAPEADO"})
# Item planejado de tipo APROPRIADO para satisfazer cada classe de requisito material.
# MEDICAO exige leitura instrumental/ensaio; DOCUMENTO exige artefato documental;
# uma atividade genérica NÃO satisfaz um requisito de medição — essa é a autoridade
# (estrutural, não textual) que impede cobertura fabricada.
_COLECOES_POR_CLASSE={"MEDICAO":("medicoes","ensaios"),"DOCUMENTO":("documentos",),
                      "INSPECAO":("atividades","fotografias","medicoes","ensaios","documentos")}

def _cobertura_semantica(dado,por_quesito):
    """Autoridade = requisitos_semanticos[].itens_planejados, validado por, para cada item:
    (existe) E (vinculado relacionalmente à cobertura do quesito) E (é de tipo apropriado
    à classe do requisito). Sem qualquer comparação textual."""
    cobertura_por_id={c.get("quesito"):c for c in dado.get("cobertura",[])}
    colecoes={chave:{item.get("id") for item in dado.get(fonte,[]) if isinstance(item,dict)}
              for chave,fonte in (("atividades","atividades"),("medicoes","medicoes"),("fotografias","fotografias"),
                                  ("ensaios","ensaios"),("documentos","documentos_a_solicitar"))}
    todos={i for ids in colecoes.values() for i in ids}
    from scripts.planejamento_pericial.requisitos_materiais import classificar_requisito
    ausente="requisitos_semanticos" not in dado
    por_quesito_sem={qid:False for qid in por_quesito};agrupados={qid:[] for qid in por_quesito}
    for r in dado.get("requisitos_semanticos",[]):
        if r.get("quesito") in agrupados:agrupados[r["quesito"]].append(r)
    total=cobertos=0;nao_mapeados=[]
    for qid,grupo in agrupados.items():
        vinculados={i for chave in colecoes for i in cobertura_por_id.get(qid,{}).get(chave,[])}
        if ausente:
            por_quesito_sem[qid]=False;total+=1;nao_mapeados.append(f"{qid}:SEM_REQUISITOS_SEMANTICOS");continue
        grupo_ok=bool(grupo)
        for r in grupo:
            total+=1
            planejados=r.get("itens_planejados") or []
            classe=r.get("classe") or classificar_requisito(r.get("requisito") or "")
            apropriadas=_COLECOES_POR_CLASSE.get(classe,("medicoes","ensaios"))
            mapeado=(r.get("status") not in _STATUS_NAO_COBRIVEL and bool(planejados) and bool(str(r.get("requisito") or "").strip()) and all(
                item_id in todos and item_id in vinculados and any(item_id in colecoes[c] for c in apropriadas)
                for item_id in planejados))
            if mapeado:cobertos+=1
            else:grupo_ok=False;nao_mapeados.append(r.get("requirement_id") or f"{qid}:{r.get('requisito','')[:40]}")
        por_quesito_sem[qid]=grupo_ok
    fracao=(cobertos/total) if total else 0.0
    return {"cobertura_requisitos_semanticos":por_quesito_sem,"total_requisitos_materiais":total,
            "requisitos_materiais_cobertos":cobertos,"requisitos_materiais_nao_mapeados":sorted(nao_mapeados),
            "cobertura_semantica_fracao":fracao}

def recalcular_cobertura(dado):
    requisitos=dado.get("requisitos_cobertura",[]);por_quesito={}
    if not requisitos:
        vazia={c["quesito"]:False for c in dado.get("cobertura",[])}
        return {"cobertura":vazia,"cobertura_relacional":vazia,"cobertura_requisitos_semanticos":vazia,
                "total_requisitos_materiais":0,"requisitos_materiais_cobertos":0,"requisitos_materiais_nao_mapeados":[],
                "cobertura_semantica_fracao":0.0,"apto":False}
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
    sem=_cobertura_semantica(dado,por_quesito)
    globais=all(satisfaz(r) for r in requisitos if r.get("obrigatoriedade")=="OBRIGATORIA")
    apto=globais and all(por_quesito.values()) and all(sem["cobertura_requisitos_semanticos"].values()) and not sem["requisitos_materiais_nao_mapeados"]
    return {"cobertura":por_quesito,"cobertura_relacional":por_quesito,"apto":apto,**sem}

def recalcular_execucao(plano,vistoria):
    """Recalcula REQUIRED→EXECUTED sem confiar no status persistido."""
    cobertura={c.get("planejado"):c for c in vistoria.get("cobertura",[]) if c.get("planejado")}
    catalogos={"ATIVIDADE":{x.get("id"):x for x in vistoria.get("atividades_executadas",[])},"FOTOGRAFIA":{x.get("id"):x for x in vistoria.get("fotografias",[])},"MEDICAO":{x.get("id"):x for x in vistoria.get("medicoes",[])},"ENSAIO":{x.get("id"):x for x in vistoria.get("ensaios",[])},"DOCUMENTO":{x.get("id"):x for x in vistoria.get("documentos_obtidos",[])}}
    campos_plano={"ATIVIDADE":"atividade_planejada","FOTOGRAFIA":"fotografia_planejada","MEDICAO":"medicao_planejada","ENSAIO":"ensaio_planejado","DOCUMENTO":"documento_planejado"}
    planejados={tipo:{x.get("id"):x for x in plano.get(chave,[]) if isinstance(x,dict)} for tipo,chave in CATALOGOS_PLANEJADOS.items()}
    faltantes=[]
    if not plano.get("requisitos_cobertura"):
        return {"apto":False,"faltantes":[{"questao_tecnica":None,"tipo":None,"item_planejado":None,"motivo":"SEM_REQUISITOS_COBERTURA"}]}
    for requisito in plano.get("requisitos_cobertura",[]):
        if requisito.get("obrigatoriedade")!="OBRIGATORIA":continue
        planejado=requisito.get("item_planejado");tipo=requisito.get("tipo");qt=requisito.get("questao_tecnica")
        item_plano=planejados.get(tipo,{}).get(planejado)
        if not item_plano or qt not in item_plano.get("questoes_tecnicas",[]):
            faltantes.append({"questao_tecnica":qt,"tipo":tipo,"item_planejado":planejado});continue
        if not planejado:
            faltantes.append({"questao_tecnica":qt,"tipo":tipo,"item_planejado":None});continue
        candidatos=[planejado]
        satisfeito=False
        for item in candidatos:
            execucao=cobertura.get(item,{})
            artefatos=[catalogos.get(tipo,{}).get(i) for i in execucao.get("executado",[])]
            direto=execucao.get("status")=="EXECUTADO" and any(a and a.get(campos_plano[tipo])==planejado and qt in a.get("questoes",a.get("questoes_tecnicas",[])) for a in artefatos)
            equivalentes=set(execucao.get("evidencia_equivalente",[]));meta=execucao.get("equivalencia") or {};todos=[(t,x) for t,cat in catalogos.items() for x in cat.values()]
            equivalentes_validos=[e for t,e in todos if t==tipo and e.get("id") in equivalentes and qt in e.get("questoes",e.get("questoes_tecnicas",[]))]
            capability_esperada=capability_item(tipo,item_plano)
            integridade_tipo=all(_medicao_equivalente(item_plano,e,qt) for e in equivalentes_validos) if tipo=="MEDICAO" else True
            equivalente=(tipo in TIPOS_EQUIVALENCIA_SUPORTADOS and execucao.get("status")=="SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE" and bool(equivalentes_validos) and integridade_tipo and
                         bool(capability_esperada) and meta.get("requisito_original")==planejado and meta.get("tipo_evidencia")==tipo and str(meta.get("capability") or "").casefold()==capability_esperada and
                         all(capability_item(tipo,e)==capability_esperada for e in equivalentes_validos) and
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
    semanticos={q for q,ok in calculada["cobertura_requisitos_semanticos"].items() if ok}
    if quesitos-semanticos: erros.append("Quesitos pertinentes sem cobertura de requisito semântico: "+", ".join(sorted(quesitos-semanticos)))
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

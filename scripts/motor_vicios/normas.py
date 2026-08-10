"""Recuperação normativa temática e temporal sem presumir requisito."""
from __future__ import annotations
from datetime import date
import operator

def _ano(valor):
    if not valor:return None
    try:return int(str(valor)[:4])
    except ValueError:return None

def aplicabilidade_temporal(norma,data_relevante=None):
    ref=_ano(data_relevante);inicio=_ano(norma.get("vigencia_inicio") or norma.get("edicao"));fim=_ano(norma.get("vigencia_fim"))
    if norma.get("status_vigencia") in {"REVOGADA","SUBSTITUIDA"} and not ref:return "APLICABILIDADE_INCONCLUSIVA"
    if ref and inicio and inicio>ref:return "APLICAVEL_COMPLEMENTAR" if norma.get("uso_retroativo")=="REFERENCIAL" else "NAO_APLICAVEL"
    if ref and fim and ref>fim:return "NAO_APLICAVEL"
    return "APLICAVEL_PRINCIPAL" if norma.get("verificada") and norma.get("requisito") else "APLICABILIDADE_INCONCLUSIVA"

def recuperar_normas_para_manifestacao(normas,*,sistema,manifestacao,mecanismo=None,questoes=None,data_relevante=None):
    termos=" ".join(filter(None,[sistema,manifestacao,mecanismo])).lower();saida=[]
    for n in normas or []:
        temas=" ".join(map(str,[n.get("sistema"),n.get("manifestacao"),n.get("titulo"),n.get("requisito")])).lower()
        rel=bool(set(termos.split()) & set(temas.split())) or sistema in n.get("sistemas",[])
        if not rel:continue
        x=dict(n);x["aplicabilidade_temporal"]=aplicabilidade_temporal(x,data_relevante);x["relevancia"]="ALTA" if x.get("requisito") and x.get("verificada") else "BAIXA";x["aspecto_suportado_pela_norma"]=x.get("aspectos_suportados",[]);saida.append(x)
    return saida

def avaliar_conformidade_normativa(norma,evidencias):
    """Compara critério verificável a dado do caso; a norma sozinha nunca prova conformidade."""
    base={"norma":norma.get("id"),"requisito":norma.get("requisito"),"metodo":norma.get("metodo_verificacao"),"criterio":norma.get("criterio"),"resultado":"INCONCLUSIVO","fundamentacao":"Não há evidência do caso suficiente para executar o método normativo.","evidencias":[]}
    if not all((norma.get("verificada"),norma.get("requisito"),norma.get("metodo_verificacao"),norma.get("criterio"),norma.get("proveniencia"))):return base
    criterio=norma["criterio"]
    if not isinstance(criterio,dict) or criterio.get("operador") not in {"<=","<",">=",">","=="} or not isinstance(criterio.get("valor"),(int,float)):return base
    candidatos=[e for e in evidencias if e.get("tipo")=="MEDICAO" and e.get("valor") is not None and (not criterio.get("grandeza") or e.get("grandeza")==criterio["grandeza"]) and (not criterio.get("unidade") or e.get("unidade")==criterio["unidade"])]
    if not candidatos:return base
    op={"<=":operator.le,"<":operator.lt,">=":operator.ge,">":operator.gt,"==":operator.eq}[criterio["operador"]];atendem=[op(e["valor"],criterio["valor"]) for e in candidatos];base.update({"resultado":"ATENDE" if all(atendem) else "NAO_ATENDE","fundamentacao":"Comparação determinística entre medição rastreável e critério normativo verificado.","evidencias":[e["id"] for e in candidatos]});return base

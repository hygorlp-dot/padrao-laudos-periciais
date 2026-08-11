"""Recuperação normativa temática e temporal sem presumir requisito."""
from __future__ import annotations
from datetime import date
import operator
from decimal import InvalidOperation
from .auditar import normalizar_medicao
from scripts.conhecimento_privado.pesquisa_online import dominio_oficial

def _ano(valor):
    if not valor:return None
    try:return int(str(valor)[:4])
    except ValueError:return None
def _data(valor):
    if not valor:return None
    try:return date.fromisoformat(str(valor)[:10])
    except ValueError:return None

def aplicabilidade_temporal(norma,data_relevante=None):
    ref_data=_data(data_relevante);inicio_data=_data(norma.get("vigencia_inicio"));fim_data=_data(norma.get("vigencia_fim") or norma.get("revogacao"))
    if ref_data and inicio_data and inicio_data>ref_data:return "APLICAVEL_COMPLEMENTAR" if norma.get("uso_retroativo")=="REFERENCIAL" else "NAO_APLICAVEL"
    if ref_data and fim_data and ref_data>fim_data:return "NAO_APLICAVEL"
    ref=_ano(data_relevante);inicio=_ano(norma.get("vigencia_inicio"));fim=_ano(norma.get("vigencia_fim") or norma.get("revogacao"))
    if not ref or not (inicio or fim):return "APLICABILIDADE_INCONCLUSIVA"
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
        x=dict(n);url=x.get("url")
        local_verificavel = (
            x.get("classificacao_fonte") in {"NORMA_TECNICA_LICENCIADA_LOCAL","FONTE_TECNICA_LOCAL_VERIFICADA"}
            and bool(x.get("proveniencia"))
            and bool(x.get("entidade"))
            and bool(x.get("numero"))
        )
        x["autoridade_fonte_verificada"]=dominio_oficial(url) if url else local_verificavel
        x["verificada"]=bool(x.get("verificada") and x["autoridade_fonte_verificada"])
        x["aplicabilidade_temporal"]=aplicabilidade_temporal(x,data_relevante);x["relevancia"]="ALTA" if x.get("requisito") and x.get("verificada") else "BAIXA";x["aspecto_suportado_pela_norma"]=x.get("aspectos_suportados",[]);saida.append(x)
    return saida

def avaliar_conformidade_normativa(norma,evidencias):
    """Compara critério verificável a dado do caso; a norma sozinha nunca prova conformidade."""
    base={"norma":norma.get("id"),"requisito":norma.get("requisito"),"metodo":norma.get("metodo_verificacao"),"criterio":norma.get("criterio"),"resultado":"INCONCLUSIVO","fundamentacao":"Não há evidência do caso suficiente para executar o método normativo.","evidencias":[]}
    aplicabilidade=norma.get("aplicabilidade_temporal")
    if aplicabilidade in {"NAO_APLICAVEL","APLICABILIDADE_INCONCLUSIVA","APLICAVEL_COMPLEMENTAR"}:return base
    if not all((norma.get("verificada"),norma.get("requisito"),norma.get("metodo_verificacao"),norma.get("criterio"),norma.get("proveniencia"))):return base
    criterio=norma["criterio"]
    if not isinstance(criterio,dict) or criterio.get("operador") not in {"<=","<",">=",">","=="} or criterio.get("valor") is None:return base
    try:valor_criterio,unidade_criterio=normalizar_medicao(criterio["valor"],criterio.get("unidade",""))
    except (InvalidOperation,ValueError):return base
    candidatos=[]
    for e in evidencias:
        if e.get("tipo")!="MEDICAO" or e.get("valor") is None or criterio.get("grandeza") and e.get("grandeza")!=criterio["grandeza"]:continue
        try:valor,unidade=normalizar_medicao(e["valor"],e.get("unidade",""))
        except (InvalidOperation,ValueError):continue
        if unidade==unidade_criterio:candidatos.append((e,valor))
    if not candidatos:return base
    op={"<=":operator.le,"<":operator.lt,">=":operator.ge,">":operator.gt,"==":operator.eq}[criterio["operador"]];atendem=[op(valor,valor_criterio) for _,valor in candidatos];base.update({"resultado":"ATENDE" if all(atendem) else "NAO_ATENDE","fundamentacao":"Comparação determinística Decimal entre valor e unidade normalizados.","evidencias":[e["id"] for e,_ in candidatos]});return base

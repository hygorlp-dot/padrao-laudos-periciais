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
    if norma.get("status_vigencia") in {"REVOGADA","SUBSTITUIDA"} and not fim_data:return "APLICABILIDADE_INCONCLUSIVA"
    if ref_data and inicio_data and inicio_data>ref_data:return "APLICAVEL_COMPLEMENTAR" if norma.get("uso_retroativo")=="REFERENCIAL" else "NAO_APLICAVEL"
    if ref_data and fim_data and ref_data>fim_data:return "NAO_APLICAVEL"
    ref=_ano(data_relevante);inicio=_ano(norma.get("vigencia_inicio"));fim=_ano(norma.get("vigencia_fim") or norma.get("revogacao"))
    if not ref or not (inicio or fim):return "APLICABILIDADE_INCONCLUSIVA"
    if ref and inicio and inicio>ref:return "APLICAVEL_COMPLEMENTAR" if norma.get("uso_retroativo")=="REFERENCIAL" else "NAO_APLICAVEL"
    if ref and fim and ref>fim:return "NAO_APLICAVEL"
    return "APLICAVEL_PRINCIPAL" if norma.get("verificada") and norma.get("requisito") else "APLICABILIDADE_INCONCLUSIVA"

def normalizar_fonte_normativa(norma,data_relevante=None):
    """Boundary único: recalcula autoridade, verificação e vigência sem confiar em flags brutas."""
    x=dict(norma or {});url=x.get("url")
    local=(x.get("classificacao_fonte") in {"NORMA_TECNICA_LICENCIADA_LOCAL","FONTE_TECNICA_LOCAL_VERIFICADA"}
           and x.get("status_verificacao")=="VERIFICADO" and bool(x.get("proveniencia"))
           and bool(x.get("entidade")) and bool(x.get("numero")))
    autoridade=dominio_oficial(url) if url else local
    x["dominio_oficial"]=dominio_oficial(url) if url else False
    x["autoridade_fonte_verificada"]=autoridade
    x["verificada"]=bool(x.get("verificada") and autoridade)
    x["aplicabilidade_temporal"]=aplicabilidade_temporal(x,data_relevante)
    x["relevancia"]="ALTA" if x.get("requisito") and x["verificada"] else "BAIXA"
    x["aspecto_suportado_pela_norma"]=x.get("aspectos_suportados",[])
    x["data_relevante"]=data_relevante or x.get("data_relevante")
    return x

def projetar_norma_pat(norma_normalizada):
    campos=("id","item","requisito","verificada","aplicabilidade_temporal","proveniencia","aspectos_suportados","edicao","pagina","tipo_requisito","metodo_verificacao","criterio","confianca")
    x={k:norma_normalizada.get(k) for k in campos};x["aspectos_suportados"]=x.get("aspectos_suportados") or ["REQUISITO_NORMATIVO_VERIFICADO"] if x.get("verificada") else []
    return x

def recuperar_normas_para_manifestacao(normas,*,sistema,manifestacao,mecanismo=None,questoes=None,data_relevante=None):
    termos=" ".join(filter(None,[sistema,manifestacao,mecanismo])).lower();saida=[]
    for n in normas or []:
        temas=" ".join(map(str,[n.get("sistema"),n.get("manifestacao"),n.get("titulo"),n.get("requisito")])).lower()
        rel=bool(set(termos.split()) & set(temas.split())) or sistema in n.get("sistemas",[])
        if not rel:continue
        saida.append(normalizar_fonte_normativa(n,data_relevante))
    return saida

def avaliar_conformidade_normativa(norma,evidencias):
    norma=normalizar_fonte_normativa(norma,norma.get("data_relevante"))
    """Compara critério verificável a dado do caso; a norma sozinha nunca prova conformidade."""
    base={"norma":norma.get("id"),"requisito":norma.get("requisito"),"metodo":norma.get("metodo_verificacao"),"criterio":norma.get("criterio"),"resultado":"INCONCLUSIVO","fundamentacao":"Não há evidência do caso suficiente para executar o método normativo.","evidencias":[]}
    aplicabilidade=norma.get("aplicabilidade_temporal")
    if aplicabilidade!="APLICAVEL_PRINCIPAL":return base
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

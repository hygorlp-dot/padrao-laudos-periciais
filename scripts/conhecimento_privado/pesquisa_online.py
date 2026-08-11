"""Recupera fonte oficial por URL direta, valida domínio e grava cache auditável."""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlparse,unquote
from urllib.request import Request,urlopen
from typing import Protocol
from dataclasses import dataclass

DOMINIOS_OFICIAIS=("abnt.org.br","gov.br","dnit.gov.br","ibape-nacional.com.br","caixa.gov.br")
PII_PADROES=(re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),re.compile(r"\b\d{11}\b"),re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),re.compile(r"\b\d{14}\b"),re.compile(r"\b(?:\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}|\d{20})\b"),re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),re.compile(r"\(?\d{2}\)?\s*\d{4,5}-?\d{4}"),re.compile(r"(?i)\b(?:rua|avenida|av\.|travessa|alameda|rodovia)\s+[\wÀ-ÿ ]+,?\s*\d+"),re.compile(r"(?i)\b(?:matr[ií]cula|inscri[cç][aã]o)\s*(?:n[.º°o]*\s*)?[\w./-]+"),re.compile(r"(?i)\b(?:parte autora|parte ré|nos autos|processo judicial|petição inicial|dados das partes)\b"))

def dados_sensiveis_processo(processo):
    valores=[]
    sensiveis={"nome","cpf_cnpj","numero_processo","endereco","matricula","email","telefone","numero_oab","cnj","cnpj","cpf"}
    containers={"endereco","representantes","advogados","partes","imovel"}
    def visitar(chave,valor,em_container=False):
        protegido=em_container or chave in containers
        if (chave in sensiveis or protegido) and isinstance(valor,(str,int)):valores.append(str(valor))
        elif isinstance(valor,dict):
            for k,v in valor.items():visitar(k,v,protegido)
        elif isinstance(valor,list):
            for v in valor:visitar(chave,v,protegido)
    visitar("",processo or {},False)
    return tuple(dict.fromkeys(v for v in valores if v.strip()))
@dataclass(frozen=True)
class EgressPolicy:
    permitir_egress: bool=False
    autorizar_dados_caso: bool=False
    dados_sensiveis: tuple[str,...]=()
    def preparar(self,consulta):
        if not self.permitir_egress:raise PermissionError("egress negado")
        inspecionada=unquote(consulta or "")
        contem_contexto=any(v and v.casefold() in inspecionada.casefold() for v in self.dados_sensiveis)
        if (contem_contexto or any(p.search(inspecionada) for p in PII_PADROES)) and not self.autorizar_dados_caso:raise PermissionError("dados de caso/PII bloqueados")
        saneada=inspecionada
        for p in PII_PADROES:saneada=p.sub("[DADO_REMOVIDO]",saneada)
        for valor in self.dados_sensiveis:
            if valor:saneada=re.sub(re.escape(valor),"[DADO_REMOVIDO]",saneada,flags=re.I)
        return saneada
def dominio_oficial(url):
    host=(urlparse(url).hostname or "").lower()
    return any(host==d or host.endswith("."+d) for d in DOMINIOS_OFICIAIS)
def pesquisar(url,destino:Path,abridor=urlopen,politica=None):
    url=(politica or EgressPolicy()).preparar(url)
    if not dominio_oficial(url):raise ValueError("domínio não reconhecido como fonte oficial")
    resposta=abridor(Request(url,headers={"User-Agent":"padrao-laudos-periciais/1.0"}),timeout=30);conteudo=resposta.read();agora=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    destino.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256(conteudo).hexdigest();arquivo=destino/(digest+".bin");arquivo.write_bytes(conteudo)
    meta={"url":url,"dominio":urlparse(url).hostname,"acessado_em":agora,"sha256":digest,"tamanho_bytes":len(conteudo),"status_vigencia":"PENDENTE_VERIFICACAO","cache":arquivo.name}
    (destino/(digest+".json")).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");return meta

class SearchProvider(Protocol):
    def buscar(self,consulta:str)->list[dict]:...

class MockSearchProvider:
    EGRESS_CAPABILITY="LOCAL_NO_EGRESS"
    def __init__(self,resultados=None,erro=None):self.resultados=resultados or [];self.erro=erro
    def buscar(self,consulta):
        if self.erro:raise self.erro
        return [dict(x) for x in self.resultados]

class AgentSearchProvider:
    """Adaptador para ferramenta de busca do agente; não recebe artefatos processuais."""
    EXTERNAL_DATA_EGRESS_REQUIRED=True
    EGRESS_CAPABILITY="EXTERNAL_EGRESS"
    def __init__(self,executor):self.executor=executor
    def buscar(self,consulta,politica=None):
        consulta=(politica or EgressPolicy()).preparar(consulta)
        if not isinstance(consulta,str) or not consulta.strip():raise ValueError("consulta pública vazia")
        return self.executor(consulta)

def buscar(consulta,provider:SearchProvider,politica=None):
    capability=getattr(provider,"EGRESS_CAPABILITY","UNKNOWN")
    if capability not in {"LOCAL_NO_EGRESS","EXTERNAL_EGRESS"}:raise PermissionError("capability de egress do provider desconhecida")
    exige=capability=="EXTERNAL_EGRESS"
    if exige and politica is None:raise PermissionError("provider externo sem EgressPolicy")
    consulta=(politica.preparar(consulta) if exige else consulta)
    resultados=provider.buscar(consulta,politica) if exige else provider.buscar(consulta);classificados=[]
    for item in resultados:
        x=dict(item);x["oficial"]=dominio_oficial(x.get("url",""));x["status_uso"]="CANDIDATA_OFICIAL" if x["oficial"] else "APENAS_DESCOBERTA";classificados.append(x)
    return sorted(classificados,key=lambda x:(not x["oficial"],x.get("url","")))

def buscar_seguro(consulta,provider:SearchProvider,politica=None):
    """Executa busca pública sem mascarar indisponibilidade ou erro HTTP."""
    try:
        saneada=(politica or EgressPolicy()).preparar(consulta)
        return {"status":"CONCLUIDA","consulta":saneada,"resultados":buscar(saneada,provider,politica),"erro":None}
    except PermissionError as exc:return {"status":"BLOQUEADO_POR_EGRESS","consulta":None,"resultados":[],"erro":str(exc)}
    except TimeoutError as exc:return {"status":"TIMEOUT","consulta":None,"resultados":[],"erro":type(exc).__name__}
    except OSError as exc:return {"status":"SEARCH_PROVIDER_INDISPONIVEL","consulta":None,"resultados":[],"erro":type(exc).__name__}
    except Exception as exc:return {"status":"ERRO_PROVIDER","consulta":None,"resultados":[],"erro":type(exc).__name__}

def cache_valido(meta,agora=None,validade_horas=24):
    try:
        acesso=datetime.fromisoformat(meta["acessado_em"]);agora=agora or datetime.now(timezone.utc).astimezone()
        if acesso.tzinfo is None:acesso=acesso.replace(tzinfo=timezone.utc)
        return agora-acesso<=timedelta(hours=validade_horas)
    except (KeyError,TypeError,ValueError):return False

def reconciliar_fontes(fontes):
    oficiais=[f for f in fontes if f.get("oficial") or dominio_oficial(f.get("url",""))]
    estado=next((f.get("status_vigencia") for f in oficiais if f.get("status_vigencia") in {"REVOGADA","SUBSTITUIDA","VIGENTE"}),"PENDENTE_VERIFICACAO")
    return {"status_vigencia":estado,"fonte_prevalente":oficiais[0].get("id") if oficiais else None,"fontes_rejeitadas":[f.get("id") for f in fontes if f not in oficiais],"conflito":len({f.get("status_vigencia") for f in fontes if f.get("status_vigencia")})>1}

def extrair_sucessao(texto,fonte_id):
    padrao=re.search(r"(?i)\b(revoga|altera|substitui)\s+(?:a\s+|o\s+)?(?:resolu[cç][aã]o|norma)?\s*([A-Z]*\s*\d+[\w./-]*)",texto or "")
    return {"fonte":fonte_id,"relacao":padrao.group(1).upper(),"alvo_textual":padrao.group(2),"status":"CANDIDATA_PENDENTE_CONFIRMACAO_OFICIAL"} if padrao else None

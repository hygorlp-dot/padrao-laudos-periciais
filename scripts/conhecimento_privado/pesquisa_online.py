"""Recupera fonte oficial por URL direta, valida domínio e grava cache auditável."""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from typing import Protocol

DOMINIOS_OFICIAIS=("abnt.org.br","gov.br","dnit.gov.br","ibape-nacional.com.br","caixa.gov.br")
def dominio_oficial(url):
    host=(urlparse(url).hostname or "").lower()
    return any(host==d or host.endswith("."+d) for d in DOMINIOS_OFICIAIS)
def pesquisar(url,destino:Path,abridor=urlopen):
    if not dominio_oficial(url):raise ValueError("domínio não reconhecido como fonte oficial")
    resposta=abridor(Request(url,headers={"User-Agent":"padrao-laudos-periciais/1.0"}),timeout=30);conteudo=resposta.read();agora=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    destino.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256(conteudo).hexdigest();arquivo=destino/(digest+".bin");arquivo.write_bytes(conteudo)
    meta={"url":url,"dominio":urlparse(url).hostname,"acessado_em":agora,"sha256":digest,"tamanho_bytes":len(conteudo),"status_vigencia":"PENDENTE_VERIFICACAO","cache":arquivo.name}
    (destino/(digest+".json")).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");return meta

class SearchProvider(Protocol):
    def buscar(self,consulta:str)->list[dict]:...

class MockSearchProvider:
    def __init__(self,resultados=None,erro=None):self.resultados=resultados or [];self.erro=erro
    def buscar(self,consulta):
        if self.erro:raise self.erro
        return [dict(x) for x in self.resultados]

class AgentSearchProvider:
    """Adaptador para ferramenta de busca do agente; não recebe artefatos processuais."""
    EXTERNAL_DATA_EGRESS_REQUIRED=True
    def __init__(self,executor):self.executor=executor
    def buscar(self,consulta):
        if not isinstance(consulta,str) or not consulta.strip():raise ValueError("consulta pública vazia")
        return self.executor(consulta)

def buscar(consulta,provider:SearchProvider):
    resultados=provider.buscar(consulta);classificados=[]
    for item in resultados:
        x=dict(item);x["oficial"]=dominio_oficial(x.get("url",""));x["status_uso"]="CANDIDATA_OFICIAL" if x["oficial"] else "APENAS_DESCOBERTA";classificados.append(x)
    return sorted(classificados,key=lambda x:(not x["oficial"],x.get("url","")))

def buscar_seguro(consulta,provider:SearchProvider):
    """Executa busca pública sem mascarar indisponibilidade ou erro HTTP."""
    try:return {"status":"CONCLUIDA","consulta":consulta,"resultados":buscar(consulta,provider),"erro":None}
    except TimeoutError as exc:return {"status":"TIMEOUT","consulta":consulta,"resultados":[],"erro":type(exc).__name__}
    except OSError as exc:return {"status":"SEARCH_PROVIDER_INDISPONIVEL","consulta":consulta,"resultados":[],"erro":type(exc).__name__}
    except Exception as exc:return {"status":"ERRO_PROVIDER","consulta":consulta,"resultados":[],"erro":type(exc).__name__}

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

"""Registra em cache privado somente fontes online já verificadas; não simula pesquisa."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

def registrar(cache:Path, *, identificador:str, tipo_fonte:str, entidade:str, titulo:str, url:str, questoes:list[str], finalidade:str, verificacoes:list[str], conteudo:bytes|None=None, edicao=None, versao=None, data_publicacao=None, vigencia=None, status_vigencia="NAO_VERIFICADA", status_uso="APENAS_DESCOBERTA"):
    if not verificacoes:raise ValueError("Fonte online sem método de verificação")
    if tipo_fonte=="FONTE_SECUNDARIA" and status_uso=="VALIDADA_PARA_USO":raise ValueError("Fonte secundária não pode fundamentar requisito normativo")
    agora=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    obj={"schema_version":"1.0.0","id":identificador,"tipo_fonte":tipo_fonte,"entidade":entidade,"titulo":titulo,"url":url,"dominio":urlparse(url).netloc.lower(),"acessado_em":agora,"edicao":edicao,"versao":versao,"data_publicacao":data_publicacao,"vigencia":vigencia,"status_vigencia":status_vigencia,"sha256":hashlib.sha256(conteudo).hexdigest() if conteudo else None,"questoes_tecnicas":questoes,"finalidade":finalidade,"confianca":{"nivel":"ALTA" if status_uso=="VALIDADA_PARA_USO" else "MEDIA"},"metodo_verificacao":verificacoes,"ultima_verificacao_online":agora,"status_uso":status_uso}
    cache.mkdir(parents=True,exist_ok=True);destino=cache/f"{identificador}.json";destino.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");return obj

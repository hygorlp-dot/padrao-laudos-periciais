"""Converte inventário privado em evidências de campo estruturadas e rastreáveis."""
from __future__ import annotations
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
RAIZ=Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:sys.path.insert(0,str(RAIZ))
from scripts.triagem_pericial.semantica import afinidade,melhores
from scripts.motor_vicios.evidencias import proposicoes_observacionais

def _vinculos(texto,plano,atividade_planejada=None):
    atividades=(plano or {}).get("atividades",[])
    candidatos=[{"id":a["id"],"descricao":" ".join(str(a.get(k) or "") for k in ("verificar","metodo","evidencia_esperada"))} for a in atividades]
    ids=[atividade_planejada] if atividade_planejada and any(a["id"]==atividade_planejada for a in atividades) else melhores(texto,candidatos) if candidatos else []
    ambiguidade=len(ids)>1
    escolhidas=[a for a in atividades if a["id"] in ids] if not ambiguidade else []
    unir=lambda campo:sorted({x for a in escolhidas for x in a.get(campo,[])})
    return {"atividade":ids[0] if len(ids)==1 else None,"questoes":unir("questoes_tecnicas"),
            "quesitos":unir("quesitos"),"alegacoes":unir("alegacoes"),
            "ambiguidade":ambiguidade,"candidatos_ambiguos":sorted(ids) if ambiguidade else []}

def _linhas(a):
    texto=a.get("metadados",{}).get("texto_original")
    if not texto:return []
    try:
        dado=json.loads(texto)
        return [x for x in (dado if isinstance(dado,list) else dado.get("registros",[dado])) if isinstance(x,dict)]
    except (ValueError,TypeError,AttributeError):pass
    if a.get("metodo_ingestao") in {"CSV","XLSX_OOXML"}:return list(csv.DictReader(io.StringIO(texto.replace(" | ",","))))
    saida=[]
    for numero_linha,linha in enumerate(texto.splitlines(),1):
        linha=linha.strip()
        if not linha:continue
        campos={}
        for parte in re.split(r"\s*[;|]\s*",linha):
            if ":" in parte or "=" in parte:
                k,v=re.split(r"[:=]",parte,maxsplit=1);campos[k.strip().lower()]=v.strip()
        if campos and ({"tipo","natureza","descricao","texto","valor","grandeza","unidade"}&set(campos)):
            saida.append(campos);continue
        declaracao=re.search(r"(?i)(?:\b(?:o\s+)?(morador|autor|autora|réu|ré|assistente|proprietário|proprietaria)\s+(?:informou|declarou|relatou|relata|disse|afirmou)\s+(?:que\s+)?|\bsegundo\s+(?:o|a)\s+(morador|autor|autora|réu|ré|proprietário|proprietaria)\s*,?\s*|\bconforme\s+relatado\s+(?:pelo|pela)\s+(morador|autor|autora|réu|ré|proprietário|proprietaria)\s*,?\s*)(.+)",linha)
        if declaracao:
            sujeito=next(x for x in declaracao.groups()[:3] if x).lower();natureza="DECLARADO_PELO_ASSISTENTE" if "assistente" in sujeito else "DECLARADO_PELA_PARTE" if sujeito in {"autor","autora","réu","ré"} else "DECLARADO_POR_TERCEIRO"
            conteudo=declaracao.group(4).strip();mista=re.search(r"(?i)(?:;|,\s*(?:e|enquanto))\s*(?:o\s+)?perito\s+(?:constatou|observou)\s+(.+)",conteudo)
            relato=conteudo[:mista.start()].strip() if mista else conteudo
            saida.append({"tipo":"DECLARACAO","descricao":relato,"declarante":sujeito,"natureza_declaracao":natureza,"trecho_fonte":linha})
            if mista:
                for proposicao in proposicoes_observacionais(mista.group(1)):
                    resultado="OBSERVADO" if proposicao["polaridade"]=="AFIRMADO" else "NAO_CONSTATADO_NA_VISTORIA" if proposicao["polaridade"]=="NEGADO" else "INCONCLUSIVO"
                    saida.append({"tipo":"OBS","descricao":proposicao["trecho_fonte"],"manifestacao":proposicao["manifestacao"],"resultado":resultado,"polaridade":proposicao["polaridade"],"metodo":"REGISTRO_DE_CAMPO"})
            continue
        local,descricao=(linha.split(":",1)+[None])[:2] if ":" in linha else (None,linha)
        proposicoes=proposicoes_observacionais(descricao)
        if proposicoes:
          for proposicao in proposicoes:
            resultado="OBSERVADO" if proposicao["polaridade"]=="AFIRMADO" else "NAO_CONSTATADO_NA_VISTORIA" if proposicao["polaridade"]=="NEGADO" else "INCONCLUSIVO"
            saida.append({"tipo":"OBS","descricao":proposicao["trecho_fonte"],"ambiente":proposicao.get("localizacao") or (local.strip() if local else None),"manifestacao":proposicao["manifestacao"],"resultado":resultado,"polaridade":proposicao["polaridade"],"metodo":"REGISTRO_DE_CAMPO","registro_id":f"{a.get('id')}:{numero_linha}"})
          med=re.search(r"(?i)(?:abertura(?:\s+medida)?\s*)?(\d+(?:[.,]\d+)?)\s*(mm|cm|m)\b",descricao)
          if med:saida.append({"tipo":"MED","grandeza":"abertura_fissura","valor":med.group(1),"unidade":med.group(2),"ambiente":local.strip() if local else None,"instrumento":None,"vinculo_registro":f"{a.get('id')}:{numero_linha}"})
    return saida
def _numero(v):
    try:return float(str(v).replace(",","."))
    except (ValueError,TypeError):return None

def _linguagem_declarativa(texto):
    return bool(re.search(r"(?i)\b(?:morador|autor(?:a)?|r[eé]u|r[eé]|propriet[aá]ri[oa]|assistente)\s+(?:informou|declarou|relatou|relata|disse|afirmou)\b|\bsegundo\s+(?:o|a)\b|\bconforme\s+relatado\b",texto or ""))

def gerar(inventario,plano=None,numero_processo=None):
    fotos=[];videos=[];docs=[];medicoes=[];observacoes=[];declaracoes=[];limitacoes=[];atividades=[];ensaios=[];equivalentes={};planejadas=(plano or {}).get("fotografias",[])
    for a in sorted(inventario["arquivos"],key=lambda x:x.get("id","")):
        meta=a.get("metadados",{})
        if a["categoria"]=="FOTOGRAFIA":
            explicitos=[p for p in planejadas if p["id"].casefold() in (a["nome"]+" "+a["caminho_relativo"]).casefold()]
            pontos=sorted([{"id":p["id"],"score":round(afinidade(a["nome"]+" "+a["caminho_relativo"],p["finalidade"]+" "+p["enquadramento"]),4)} for p in planejadas],key=lambda x:(-x["score"],x["id"]));ambiguo=not explicitos and len(pontos)>1 and pontos[0]["score"]>0 and abs(pontos[0]["score"]-pontos[1]["score"])<=0.05;melhor={"id":explicitos[0]["id"],"score":1.0} if len(explicitos)==1 else pontos[0] if pontos and pontos[0]["score"]>0 and not ambiguo else None
            plano_foto=next((p for p in planejadas if melhor and p["id"]==melhor["id"]),{})
            fotos.append({"id":f"FOT-{len(fotos)+1:03d}","arquivo_inventario":a["id"],"fotografia_planejada":melhor["id"] if melhor else None,"finalidade_planejada":plano_foto.get("finalidade"),"descricao_visual_observada":None,"estado_interpretacao":"NAO_INTERPRETADA","candidatos_planejamento":pontos,"metodo_associacao":"ID_PLANEJADO_EXPLICITO" if explicitos else "ASSOCIACAO_AMBIGUA" if ambiguo else "AFINIDADE_SEMANTICA_NOME_FINALIDADE" if melhor else "SEM_ASSOCIACAO_SEGURA","data_hora":meta.get("data_hora_captura"),"coordenadas":meta.get("coordenadas"),"orientacao":meta.get("orientacao"),"ambiente":plano_foto.get("ambiente"),"sistema":plano_foto.get("sistema"),"descricao_objetiva":None,"atividade":plano_foto.get("atividade"),"questoes":plano_foto.get("questoes_tecnicas",[]),"quesitos":plano_foto.get("quesitos",[]),"alegacoes":plano_foto.get("alegacoes",[]),"confianca":{"nivel":"BAIXA" if ambiguo or not melhor else "MEDIA"},"proveniencia":[a["id"]]})
        elif a["categoria"]=="VIDEO":videos.append({"id":f"VID-{len(videos)+1:03d}","arquivo_inventario":a["id"],"data_hora":meta.get("data_hora_captura"),"ambiente":None,"atividade":None,"questoes":[],"alegacoes":[],"proveniencia":[a["id"]]})
        elif a["categoria"]=="DOCUMENTO":
            explicitos=[p["id"] for p in (plano or {}).get("documentos_a_solicitar",[]) if p["id"].casefold() in (a["nome"]+" "+a["caminho_relativo"]).casefold()]
            planejado=meta.get("documento_planejado") or (explicitos[0] if len(explicitos)==1 else None)
            item=next((p for p in (plano or {}).get("documentos_a_solicitar",[]) if p.get("id")==planejado),{})
            docs.append({"id":f"DOC-VIS-{len(docs)+1:03d}","arquivo_inventario":a["id"],"documento_planejado":planejado if item else None,"descricao":a["nome"],"questoes":item.get("questoes_tecnicas",[]),"proveniencia":[a["id"]]})
        for r in _linhas(a):
            tipo=str(r.get("tipo") or r.get("natureza") or "").upper();valor=_numero(r.get("valor"));descricao=r.get("descricao") or r.get("texto")
            if valor is not None and r.get("grandeza") and r.get("unidade"):
                planejada=next((x for x in (plano or {}).get("medicoes",[]) if x.get("id")==r.get("medicao_planejada")),{})
                medicoes.append({"id":f"MED-{len(medicoes)+1:03d}","medicao_planejada":r.get("medicao_planejada"),"grandeza":r["grandeza"],"valor":valor,"unidade":r["unidade"],"local":r.get("local"),"ambiente":r.get("ambiente"),"sistema":r.get("sistema"),"instrumento":r.get("instrumento"),"precisao":r.get("precisao"),"data_hora":r.get("data_hora"),"responsavel":r.get("responsavel"),"metodo":r.get("metodo","REGISTRO_DE_CAMPO"),"questoes":planejada.get("questoes_tecnicas",[]),"quesitos":planejada.get("quesitos",[]),"alegacoes":planejada.get("alegacoes",[]),"observacoes":[],"fotografias":[],"proveniencia":[a["id"]],"_vinculo_registro":r.get("vinculo_registro") or r.get("observacao_ref")});continue
            if tipo in {"ATV","ATIVIDADE"} and descricao:
                planejada=next((x for x in (plano or {}).get("atividades",[]) if x.get("id")==r.get("atividade_planejada")),{})
                atividades.append({"id":f"ATV-EXEC-{len(atividades)+1:03d}","atividade_planejada":r.get("atividade_planejada"),"descricao":descricao,"status":r.get("status","EXECUTADO"),"questoes":planejada.get("questoes_tecnicas",[]),"evidencias":[a["id"]],"impacto_nao_execucao":None});continue
            if tipo in {"ENS","ENSAIO"} and descricao:
                planejado=r.get("ensaio_planejado");item=next((p for p in (plano or {}).get("ensaios",[]) if p.get("id")==planejado),{})
                ensaios.append({"id":f"ENS-{len(ensaios)+1:03d}","ensaio_planejado":planejado if item else None,"nome":descricao,"status":r.get("status","EXECUTADO"),"resultado":r.get("resultado"),"unidade":r.get("unidade"),"metodo":r.get("metodo"),"questoes":item.get("questoes_tecnicas",[]),"proveniencia":[a["id"]]});continue
            if tipo.startswith("DECLAR") and descricao:declaracoes.append({"id":f"DEC-VIS-{len(declaracoes)+1:03d}","natureza":r.get("natureza_declaracao","DECLARADO_POR_TERCEIRO"),"declarante":r.get("declarante"),"texto_original":descricao,"questoes":[],"alegacoes":[],"proveniencia":[a["id"]]})
            elif tipo.startswith("LIMIT") and descricao:limitacoes.append({"id":f"LIM-{len(limitacoes)+1:03d}","descricao":descricao,"campo_afetado":r.get("campo_afetado"),"consequencia_tecnica":r.get("consequencia","Extensão da análise limitada ao campo efetivamente acessível.")})
            elif tipo in {"OBS","OBSERVACAO","CONSTATAÇÃO","CONSTATACAO"} and descricao:
                if _linguagem_declarativa(descricao):
                    declaracoes.append({"id":f"DEC-VIS-{len(declaracoes)+1:03d}","natureza":"DECLARADO_POR_TERCEIRO","declarante":r.get("declarante"),"texto_original":descricao,"questoes":[],"alegacoes":[],"proveniencia":[a["id"]]});continue
                vinculos=_vinculos(descricao,plano,r.get("atividade_planejada"))
                if vinculos["atividade"] and not any(x.get("atividade_planejada")==vinculos["atividade"] for x in atividades):
                    atividades.append({"id":f"ATV-EXEC-{len(atividades)+1:03d}","atividade_planejada":vinculos["atividade"],"descricao":"Atividade documentada por observação de campo rastreável.","status":"EXECUTADO","questoes":vinculos["questoes"],"evidencias":[a["id"]],"impacto_nao_execucao":None})
                aspectos=r.get("aspectos_suportados",[])
                if isinstance(aspectos,str):aspectos=[x.strip() for x in aspectos.split(",") if x.strip()]
                proposicoes=proposicoes_observacionais(descricao);polaridades={p["polaridade"] for p in proposicoes};resultado=r.get("resultado","OBSERVADO")
                if polaridades=={"NEGADO"}:resultado="NAO_CONSTATADO_NA_VISTORIA"
                elif polaridades and polaridades<={"INCERTO","HIPOTETICO"}:resultado="INCONCLUSIVO"
                observacoes.append({"id":f"OBS-{len(observacoes)+1:03d}","local":r.get("local"),"ambiente":r.get("ambiente"),"sistema":r.get("sistema"),"elemento":r.get("elemento"),"descricao_objetiva":descricao,"manifestacao":r.get("manifestacao") or (proposicoes[0]["manifestacao"] if len(proposicoes)==1 else None),"resultado":resultado,"campo_examinado":r.get("campo_examinado","Campo descrito na anotação estruturada"),"metodo":[r.get("metodo","REGISTRO_DE_CAMPO")],"atividade":vinculos["atividade"],"fotografias":[],"medicoes":[],"alegacoes":vinculos["alegacoes"],"questoes":vinculos["questoes"],"quesitos":vinculos["quesitos"],"confianca":{"nivel":"MEDIA"},"proveniencia":[a["id"]],"limitacoes":[],"aspectos_suportados":aspectos,"_registro_id":r.get("registro_id")})
    relacoes=[]
    def univocos(itens,campo):
        grupos={}
        for item in itens:
            if item.get(campo):grupos.setdefault(item[campo],[]).append(item["id"])
        return {chave:ids[0] for chave,ids in grupos.items() if len(ids)==1}
    registros=univocos(observacoes,"_registro_id")
    atividades_univocas=univocos(observacoes,"atividade")
    for obs in observacoes:
        def comp(item):
            explicito=obs["id"] in item.get("observacoes",[])
            registro=bool(item.get("_vinculo_registro") and registros.get(item["_vinculo_registro"])==obs["id"])
            atividade_univoca=bool(item.get("atividade") and atividades_univocas.get(item["atividade"])==obs["id"])
            atividade=bool(obs.get("atividade") and item.get("atividade") and item.get("atividade")==obs.get("atividade"))
            # TODO(#74): normalizar() is undefined here -- dormant NameError risk,
            # currently unreachable because no producer sets "elemento" on
            # medicoes/fotos. Do not add an "elemento" key without resolving #74.
            elemento=bool(obs.get("elemento") and item.get("elemento") and normalizar(obs.get("elemento"))==normalizar(item.get("elemento")))
            manifestacao=bool(obs.get("manifestacao") and item.get("manifestacao") and normalizar(obs.get("manifestacao"))==normalizar(item.get("manifestacao")))
            return explicito or registro or atividade_univoca or (atividade and elemento and manifestacao)
        obs["medicoes"]=sorted(m["id"] for m in medicoes if comp(m));obs["fotografias"]=sorted(f["id"] for f in fotos if comp(f))
        for eid in obs["medicoes"]+obs["fotografias"]:
            item=next(x for x in medicoes+fotos if x["id"]==eid)
            if obs["id"] in item.get("observacoes",[]):motivo,origem="VINCULO_EXPLICITO","ENTRADA_ESTRUTURADA"
            elif item.get("_vinculo_registro") and registros.get(item["_vinculo_registro"])==obs["id"]:motivo,origem="VINCULO_REGISTRO_EXPLICITO","REGISTRO_CAMPO_COMUM"
            elif item.get("atividade") and atividades_univocas.get(item["atividade"])==obs["id"]:motivo,origem="ATIVIDADE_PLANEJADA_UNIVOCA","PLANO_VISTORIA"
            else:motivo,origem="ATIVIDADE_ELEMENTO_MANIFESTACAO_CONVERGENTES","ENTRADA_ESTRUTURADA"
            relacoes.append({"observacao":obs["id"],"evidencia":eid,"motivo":motivo,"origem":origem})
        for med in medicoes:
            if med["id"] in obs["medicoes"]:med["observacoes"]=sorted(set(med["observacoes"]+[obs["id"]]))
    for obs in observacoes:obs.pop("_registro_id",None)
    for med in medicoes:med.pop("_vinculo_registro",None)
    executados={"FOTOGRAFIA":{f["fotografia_planejada"]:f["id"] for f in fotos if f["fotografia_planejada"]},"MEDICAO":{m["medicao_planejada"]:m["id"] for m in medicoes if m["medicao_planejada"]},"ATIVIDADE":{a["atividade_planejada"]:a["id"] for a in atividades if a["atividade_planejada"]},"ENSAIO":{},"DOCUMENTO":{}}
    for e in ensaios:
        p=next((p for p in (plano or {}).get("ensaios",[]) if e.get("ensaio_planejado")==p["id"]),None)
        if p:executados["ENSAIO"][p["id"]]=e["id"]
    for d in docs:
        p=next((p for p in (plano or {}).get("documentos_a_solicitar",[]) if d.get("documento_planejado")==p["id"]),None)
        if p:executados["DOCUMENTO"][p["id"]]=d["id"]
    cobertura=[]
    if plano:
        for tipo,chave in (("ATIVIDADE","atividades"),("MEDICAO","medicoes"),("FOTOGRAFIA","fotografias"),("ENSAIO","ensaios"),("DOCUMENTO","documentos_a_solicitar")):
            for x in plano.get(chave,[]):
                pid=x.get("id") if isinstance(x,dict) else str(x);achado=executados[tipo].get(pid);status="EXECUTADO" if achado else "NAO_EXECUTADO";cobertura.append({"tipo":tipo,"planejado":pid,"status":status,"executado":[achado] if achado else [],"evidencia_equivalente":[],"equivalencia":None,"justificativa_equivalencia":None,"impacto":None if achado else "Ausência ainda não avaliada tecnicamente."})
    return {"schema_version":"2.0.0","numero_processo":numero_processo or "0000000-00.0000.0.00.0000","status":"VISTORIA_ESTRUTURADA" if inventario["arquivos"] else "AGUARDANDO_DADOS_DE_VISTORIA","data":None,"hora_inicio":None,"hora_fim":None,"local":None,"coordenadas":None,"condicoes":{"clima":None,"temperatura":None,"umidade_relativa":None,"campo_examinado":None},"participantes":[],"atividades_executadas":atividades,"equipamentos":[],"limitacoes":limitacoes,"fotografias":fotos,"videos":videos,"medicoes":medicoes,"ensaios":ensaios,"documentos_obtidos":docs,"declaracoes":declaracoes,"observacoes":observacoes,"relacoes_evidencia":relacoes,"cobertura":cobertura,"inventario_fonte":"inventario-vistoria.json","proveniencia":["inventario-vistoria.json"]}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inventario",type=Path);p.add_argument("--plano",type=Path);p.add_argument("--processo");p.add_argument("--saida",type=Path);a=p.parse_args();inv=json.loads(a.inventario.read_text(encoding="utf-8"));pl=json.loads(a.plano.read_text(encoding="utf-8")) if a.plano else None;out=a.saida or a.inventario.parent/"vistoria.json";out.write_text(json.dumps(gerar(inv,pl,a.processo),ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(out);return 0
if __name__=="__main__":raise SystemExit(main())

"""Converte inventário privado em evidências de campo estruturadas e rastreáveis."""
from __future__ import annotations
import argparse,csv,io,json,re,sys
from pathlib import Path
RAIZ=Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:sys.path.insert(0,str(RAIZ))
from scripts.triagem_pericial.semantica import afinidade,melhores
from scripts.motor_vicios.evidencias import proposicoes_observacionais

def _vinculos(texto,plano,atividade_planejada=None):
    atividades=(plano or {}).get("atividades",[])
    candidatos=[{"id":a["id"],"descricao":" ".join(str(a.get(k) or "") for k in ("verificar","metodo","evidencia_esperada"))} for a in atividades]
    ids=[atividade_planejada] if atividade_planejada and any(a["id"]==atividade_planejada for a in atividades) else melhores(texto,candidatos) if candidatos else []
    escolhidas=[a for a in atividades if a["id"] in ids]
    unir=lambda campo:sorted({x for a in escolhidas for x in a.get(campo,[])})
    return {"atividade":ids[0] if len(ids)==1 else None,"questoes":unir("questoes_tecnicas"),
            "quesitos":unir("quesitos"),"alegacoes":unir("alegacoes")}

def _linhas(a):
    texto=a.get("metadados",{}).get("texto_original")
    if not texto:return []
    try:
        dado=json.loads(texto)
        return [x for x in (dado if isinstance(dado,list) else dado.get("registros",[dado])) if isinstance(x,dict)]
    except (ValueError,TypeError,AttributeError):pass
    if a.get("metodo_ingestao") in {"CSV","XLSX_OOXML"}:return list(csv.DictReader(io.StringIO(texto.replace(" | ",","))))
    saida=[]
    for linha in texto.splitlines():
        linha=linha.strip()
        if not linha:continue
        campos={}
        for parte in re.split(r"\s*[;|]\s*",linha):
            if ":" in parte or "=" in parte:
                k,v=re.split(r"[:=]",parte,maxsplit=1);campos[k.strip().lower()]=v.strip()
        if campos and ({"tipo","natureza","descricao","texto","valor","grandeza","unidade"}&set(campos)):
            saida.append(campos);continue
        declaracao=re.search(r"(?i)\b(morador|autor|autora|réu|ré|assistente|proprietário|proprietaria|proprietário)\s+(?:informou|declarou|relatou|disse)\s+(?:que\s+)?(.+)",linha)
        if declaracao:
            sujeito=declaracao.group(1).lower();natureza="DECLARADO_PELO_ASSISTENTE" if "assistente" in sujeito else "DECLARADO_PELA_PARTE" if sujeito in {"autor","autora","réu","ré"} else "DECLARADO_POR_TERCEIRO"
            saida.append({"tipo":"DECLARACAO","descricao":linha,"declarante":declaracao.group(1),"natureza_declaracao":natureza});continue
        local,descricao=(linha.split(":",1)+[None])[:2] if ":" in linha else (None,linha)
        proposicoes=proposicoes_observacionais(descricao)
        if proposicoes:
          for proposicao in proposicoes:
            resultado="OBSERVADO" if proposicao["polaridade"]=="AFIRMADO" else "NAO_CONSTATADO_NA_VISTORIA" if proposicao["polaridade"]=="NEGADO" else "INCONCLUSIVO"
            saida.append({"tipo":"OBS","descricao":proposicao["trecho_fonte"],"ambiente":proposicao.get("localizacao") or (local.strip() if local else None),"manifestacao":proposicao["manifestacao"],"resultado":resultado,"polaridade":proposicao["polaridade"],"metodo":"REGISTRO_DE_CAMPO"})
          med=re.search(r"(?i)(?:abertura(?:\s+medida)?\s*)?(\d+(?:[.,]\d+)?)\s*(mm|cm|m)\b",descricao)
          if med:saida.append({"tipo":"MED","grandeza":"abertura_fissura","valor":med.group(1),"unidade":med.group(2),"ambiente":local.strip() if local else None,"instrumento":None})
    return saida
def _numero(v):
    try:return float(str(v).replace(",","."))
    except (ValueError,TypeError):return None

def gerar(inventario,plano=None,numero_processo=None):
    fotos=[];videos=[];docs=[];medicoes=[];observacoes=[];declaracoes=[];limitacoes=[];atividades=[];ensaios=[];equivalentes={};planejadas=(plano or {}).get("fotografias",[])
    for a in inventario["arquivos"]:
        meta=a.get("metadados",{})
        if a["categoria"]=="FOTOGRAFIA":
            pontos=sorted([{"id":p["id"],"score":round(afinidade(a["nome"]+" "+a["caminho_relativo"],p["finalidade"]+" "+p["enquadramento"]),4)} for p in planejadas],key=lambda x:(-x["score"],x["id"]));ambiguo=len(pontos)>1 and pontos[0]["score"]>0 and abs(pontos[0]["score"]-pontos[1]["score"])<=0.05;melhor=pontos[0] if pontos and pontos[0]["score"]>0 and not ambiguo else None
            plano_foto=next((p for p in planejadas if melhor and p["id"]==melhor["id"]),{})
            fotos.append({"id":f"FOT-{len(fotos)+1:03d}","arquivo_inventario":a["id"],"fotografia_planejada":melhor["id"] if melhor else None,"finalidade_planejada":plano_foto.get("finalidade"),"descricao_visual_observada":None,"estado_interpretacao":"NAO_INTERPRETADA","candidatos_planejamento":pontos,"metodo_associacao":"ASSOCIACAO_AMBIGUA" if ambiguo else "AFINIDADE_SEMANTICA_NOME_FINALIDADE" if melhor else "SEM_ASSOCIACAO_SEGURA","data_hora":meta.get("data_hora_captura"),"coordenadas":meta.get("coordenadas"),"orientacao":meta.get("orientacao"),"ambiente":plano_foto.get("ambiente"),"sistema":plano_foto.get("sistema"),"descricao_objetiva":None,"atividade":plano_foto.get("atividade"),"questoes":plano_foto.get("questoes_tecnicas",[]),"quesitos":plano_foto.get("quesitos",[]),"alegacoes":plano_foto.get("alegacoes",[]),"confianca":{"nivel":"BAIXA" if ambiguo or not melhor else "MEDIA"},"proveniencia":[a["id"]]})
        elif a["categoria"]=="VIDEO":videos.append({"id":f"VID-{len(videos)+1:03d}","arquivo_inventario":a["id"],"data_hora":meta.get("data_hora_captura"),"ambiente":None,"atividade":None,"questoes":[],"alegacoes":[],"proveniencia":[a["id"]]})
        elif a["categoria"]=="DOCUMENTO":docs.append({"id":f"DOC-VIS-{len(docs)+1:03d}","arquivo_inventario":a["id"],"descricao":a["nome"],"proveniencia":[a["id"]]})
        for r in _linhas(a):
            tipo=str(r.get("tipo") or r.get("natureza") or "").upper();valor=_numero(r.get("valor"));descricao=r.get("descricao") or r.get("texto")
            if valor is not None and r.get("grandeza") and r.get("unidade"):
                medicoes.append({"id":f"MED-{len(medicoes)+1:03d}","medicao_planejada":r.get("medicao_planejada"),"grandeza":r["grandeza"],"valor":valor,"unidade":r["unidade"],"local":r.get("local"),"ambiente":r.get("ambiente"),"sistema":r.get("sistema"),"instrumento":r.get("instrumento"),"precisao":r.get("precisao"),"data_hora":r.get("data_hora"),"responsavel":r.get("responsavel"),"metodo":r.get("metodo","REGISTRO_DE_CAMPO"),"questoes":[],"quesitos":[],"alegacoes":[],"observacoes":[],"fotografias":[],"proveniencia":[a["id"]]});continue
            if tipo in {"ATV","ATIVIDADE"} and descricao:atividades.append({"id":f"ATV-EXEC-{len(atividades)+1:03d}","atividade_planejada":r.get("atividade_planejada"),"descricao":descricao,"status":r.get("status","EXECUTADO"),"evidencias":[a["id"]],"impacto_nao_execucao":None});continue
            if tipo in {"ENS","ENSAIO"} and descricao:ensaios.append({"id":f"ENS-{len(ensaios)+1:03d}","nome":descricao,"status":r.get("status","EXECUTADO"),"resultado":r.get("resultado"),"unidade":r.get("unidade"),"metodo":r.get("metodo"),"questoes":[],"proveniencia":[a["id"]]});continue
            if r.get("substitui_planejado"):equivalentes.setdefault(r["substitui_planejado"],[]).append(a["id"])
            if tipo.startswith("DECLAR") and descricao:declaracoes.append({"id":f"DEC-VIS-{len(declaracoes)+1:03d}","natureza":r.get("natureza_declaracao","DECLARADO_POR_TERCEIRO"),"declarante":r.get("declarante"),"texto_original":descricao,"questoes":[],"alegacoes":[],"proveniencia":[a["id"]]})
            elif tipo.startswith("LIMIT") and descricao:limitacoes.append({"id":f"LIM-{len(limitacoes)+1:03d}","descricao":descricao,"campo_afetado":r.get("campo_afetado"),"consequencia_tecnica":r.get("consequencia","Extensão da análise limitada ao campo efetivamente acessível.")})
            elif tipo in {"OBS","OBSERVACAO","CONSTATAÇÃO","CONSTATACAO"} and descricao:
                vinculos=_vinculos(descricao,plano,r.get("atividade_planejada"))
                aspectos=r.get("aspectos_suportados",[])
                if isinstance(aspectos,str):aspectos=[x.strip() for x in aspectos.split(",") if x.strip()]
                proposicoes=proposicoes_observacionais(descricao);polaridades={p["polaridade"] for p in proposicoes};resultado=r.get("resultado","OBSERVADO")
                if polaridades=={"NEGADO"}:resultado="NAO_CONSTATADO_NA_VISTORIA"
                elif polaridades and polaridades<={"INCERTO","HIPOTETICO"}:resultado="INCONCLUSIVO"
                observacoes.append({"id":f"OBS-{len(observacoes)+1:03d}","local":r.get("local"),"ambiente":r.get("ambiente"),"sistema":r.get("sistema"),"elemento":r.get("elemento"),"descricao_objetiva":descricao,"manifestacao":r.get("manifestacao") or (proposicoes[0]["manifestacao"] if len(proposicoes)==1 else None),"resultado":resultado,"campo_examinado":r.get("campo_examinado","Campo descrito na anotação estruturada"),"metodo":[r.get("metodo","REGISTRO_DE_CAMPO")],"fotografias":[],"medicoes":[],"alegacoes":vinculos["alegacoes"],"questoes":vinculos["questoes"],"quesitos":vinculos["quesitos"],"confianca":{"nivel":"MEDIA"},"proveniencia":[a["id"]],"limitacoes":[],"aspectos_suportados":aspectos})
    for obs in observacoes:
        def comp(item):
            return bool(obs.get("ambiente") and item.get("ambiente")==obs.get("ambiente")) or item.get("proveniencia")==obs.get("proveniencia") or bool(set(item.get("questoes",[]))&set(obs.get("questoes",[])))
        obs["medicoes"]=sorted(m["id"] for m in medicoes if comp(m));obs["fotografias"]=sorted(f["id"] for f in fotos if comp(f))
        for med in medicoes:
            if med["id"] in obs["medicoes"]:med["observacoes"]=sorted(set(med["observacoes"]+[obs["id"]]))
    executados={"FOTOGRAFIA":{f["fotografia_planejada"]:f["id"] for f in fotos if f["fotografia_planejada"]},"MEDICAO":{m["medicao_planejada"]:m["id"] for m in medicoes if m["medicao_planejada"]},"ATIVIDADE":{a["atividade_planejada"]:a["id"] for a in atividades if a["atividade_planejada"]},"ENSAIO":{},"DOCUMENTO":{}}
    for e in ensaios:
        for p in (plano or {}).get("ensaios",[]):
            if afinidade(e["nome"],p.get("nome") or p.get("descricao") or "")>0:executados["ENSAIO"][p["id"]]=e["id"]
    for d in docs:
        for p in (plano or {}).get("documentos_a_solicitar",[]):
            pid=p.get("id") if isinstance(p,dict) else str(p);texto=p.get("descricao","") if isinstance(p,dict) else str(p)
            if afinidade(d["descricao"],texto)>0:executados["DOCUMENTO"][pid]=d["id"]
    cobertura=[]
    if plano:
        for tipo,chave in (("ATIVIDADE","atividades"),("MEDICAO","medicoes"),("FOTOGRAFIA","fotografias"),("ENSAIO","ensaios"),("DOCUMENTO","documentos_a_solicitar")):
            for x in plano.get(chave,[]):
                pid=x.get("id") if isinstance(x,dict) else str(x);achado=executados[tipo].get(pid);eq=equivalentes.get(pid,[]);status="EXECUTADO" if achado else "SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE" if eq else "NAO_EXECUTADO";cobertura.append({"tipo":tipo,"planejado":pid,"status":status,"executado":[achado] if achado else [],"evidencia_equivalente":eq,"impacto":None if achado or eq else "Ausência ainda não avaliada tecnicamente."})
    return {"schema_version":"2.0.0","numero_processo":numero_processo or "0000000-00.0000.0.00.0000","status":"VISTORIA_ESTRUTURADA" if inventario["arquivos"] else "AGUARDANDO_DADOS_DE_VISTORIA","data":None,"hora_inicio":None,"hora_fim":None,"local":None,"coordenadas":None,"condicoes":{"clima":None,"temperatura":None,"umidade_relativa":None,"campo_examinado":None},"participantes":[],"atividades_executadas":atividades,"equipamentos":[],"limitacoes":limitacoes,"fotografias":fotos,"videos":videos,"medicoes":medicoes,"ensaios":ensaios,"documentos_obtidos":docs,"declaracoes":declaracoes,"observacoes":observacoes,"cobertura":cobertura,"inventario_fonte":"inventario-vistoria.json","proveniencia":["inventario-vistoria.json"]}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inventario",type=Path);p.add_argument("--plano",type=Path);p.add_argument("--processo");p.add_argument("--saida",type=Path);a=p.parse_args();inv=json.loads(a.inventario.read_text(encoding="utf-8"));pl=json.loads(a.plano.read_text(encoding="utf-8")) if a.plano else None;out=a.saida or a.inventario.parent/"vistoria.json";out.write_text(json.dumps(gerar(inv,pl,a.processo),ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(out);return 0
if __name__=="__main__":raise SystemExit(main())

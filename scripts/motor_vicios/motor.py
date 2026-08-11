"""Orquestra manifestações, hipóteses, PAT, saneamento, quesitos e gate de redação."""

from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from scripts.triagem_pericial.semantica import intencoes
from .auditar import auditar
from .hipoteses import gerar as gerar_hipoteses,capacidade_causal
from .regras import situacao,classificacoes,inferir_origem,avaliar_consequencias,derivar_criticidade,estruturar_reparo,tipo_vicio
from .evidencias import construir_catalogo,selecionar
from .normas import recuperar_normas_para_manifestacao,avaliar_conformidade_normativa

def _consequencias():return {k:None for k in ("seguranca","funcionalidade","estanqueidade","salubridade","higiene","durabilidade","conforto","estetica","manutencao","evolucao")}
def _identidade_manifestacao(obs,chave):
    numeros=[int(m.group(1)) for o in obs if (m:=re.fullmatch(r"OBS-(\d+)",o.get("id","")))]
    return f"{min(numeros):03d}" if numeros else str(int(hashlib.sha256(repr(chave).encode()).hexdigest()[:12],16))

def _base(processo,delimitacao,status,tipo):
    quesitos=[]
    for q in delimitacao.get("quesitos",[]):
        jurid=q.get("pertinencia")=="NAO_PERTINENTE_JURIDICO" or bool(q.get("materia_juridica_associada"))
        quesitos.append({"quesito":q["id"],"status":"MATERIA_JURIDICA" if jurid else "PENDENTE_EVIDENCIA","questoes":q.get("questoes_tecnicas_relacionadas",[]),"patologias":[],"observacoes":[],"fotografias":[],"medicoes":[],"hipoteses":[],"normas":[],"ressalvas":[]})
    return {"schema_version":"1.0.0","processo_cnj":processo["numero_processo"],"tipo_pericia":tipo,"status_execucao":status,"manifestacoes":[],"hipoteses":[],"patologias":[],"questoes_saneadas":[],"cobertura_quesitos":quesitos,"pesquisa_online":{"status":"NAO_NECESSARIA","pesquisas_realizadas":0,"fontes_oficiais_localizadas":[],"fontes_rejeitadas":[],"fontes_cacheadas":[],"revalidacoes_vigencia":0,"pesquisas_desnecessarias_evitadas":1},"autoauditoria":[],"autonomia":{"decisoes_autonomas":1,"hipoteses_criadas":0,"hipoteses_testadas":0,"pesquisas_autonomas":0,"normas_recuperadas":0,"fontes_online_recuperadas":0,"lacunas_resolvidas":0,"ressalvas_criadas":0,"perguntas_evitadas":["Não solicitar informação rotineira sem evidência de campo."],"perguntas_necessarias":[]},"gate_redacao":"BLOQUEADO_PARA_REDACAO","proveniencia":["processo.json","delimitacao-pericial.json"]}

def executar(processo,delimitacao,plano,vistoria,contexto=None,conhecimento=None):
    tipo=delimitacao["tipo_pericia"]["tipo"]
    if tipo!="VICIOS_CONSTRUTIVOS":return _base(processo,delimitacao,"MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO",tipo)
    if vistoria.get("status")=="AGUARDANDO_DADOS_DE_VISTORIA" or not vistoria.get("observacoes"):
        return _base(processo,delimitacao,"AGUARDANDO_DADOS_DE_VISTORIA",tipo)
    r=_base(processo,delimitacao,"ANALISE_INICIAL",tipo); contexto=contexto or {};conhecimento=conhecimento or {};catalogo=construir_catalogo(vistoria,conhecimento.get("documentos"),conhecimento.get("normas"));r["catalogo_evidencias"]=catalogo;r["estado_analise"]="PAT_INICIAL"; por_manifestacao={}
    for o in vistoria["observacoes"]:
        chave=(o.get("manifestacao") or "Condição examinada",o.get("ambiente"),o.get("sistema"),o.get("elemento"));por_manifestacao.setdefault(chave,[]).append(o)
    hip_seq=1
    for idx,chave in enumerate(sorted(por_manifestacao,key=lambda x:tuple(str(v or "").casefold() for v in x)),1):
        obs=sorted(por_manifestacao[chave],key=lambda x:x.get("id", ""))
        desc,amb,sis,elem=chave;capacidade=capacidade_causal(sis);sem_motor=capacidade["nivel_de_capacidade"]=="MOTOR_CAUSAL_NAO_IMPLEMENTADO";sufixo=_identidade_manifestacao(obs,chave);idx=int(sufixo);mid=f"MAN-{sufixo}";alg=sorted({x for o in obs for x in o["alegacoes"]});fot=sorted({x for o in obs for x in o["fotografias"]});med=sorted({x for o in obs for x in o["medicoes"]});qts=sorted({x for o in obs for x in o["questoes"]});oids=[o["id"] for o in obs]
        r["manifestacoes"].append({"id":mid,"descricao":desc,"sistema":sis,"elemento":elem,"local":amb,"alegacoes":alg,"observacoes":oids,"fotografias":fot,"medicoes":med,"questoes":qts})
        ctx=contexto.get(mid,{}) if contexto.get("_modo")=="OVERRIDE_EXPLICITO" else {};evidencias_man=selecionar(catalogo,ids=[o["id"] for o in obs]+fot+med,sistema=sis,manifestacao=desc,contexto={"questoes":qts,"sistema":sis,"manifestacao":desc,"ambiente":amb,"elemento":elem,"alegacoes":alg},relacao_id=mid);normas=recuperar_normas_para_manifestacao(conhecimento.get("normas",[]),sistema=sis,manifestacao=desc,questoes=qts,data_relevante=conhecimento.get("data_relevante"));sit=situacao(obs)
        hips=gerar_hipoteses(desc,mid,ctx.get("evidencias_hipoteses",{}),ctx.get("evidencias_ausentes",[]),hip_seq,sistema=sis,catalogo=evidencias_man,normas=normas) if sit in {"ANOMALIA","FALHA","INCONCLUSIVA"} else []
        hip_seq+=len(hips);r["hipoteses"].extend(hips)
        mais=next((h for h in hips if h["status"]=="MAIS_PROVAVEL"),None);causa=mais["causa_candidata"] if mais else None;mec=mais["mecanismo"] if mais else None;fundamentos=mais["evidencias_favoraveis"] if mais else []
        origem_inferida=inferir_origem(causa,evidencias_man);consequencias=avaliar_consequencias(sit,evidencias_man);criticidade,fund_criticidade=derivar_criticidade(sit,consequencias);reparo=estruturar_reparo(causa,sis,evidencias_man);causalidade={"causa":causa,"origem":origem_inferida,"evidencias":fundamentos,"criticidade":criticidade,"fundamentacao_criticidade":fund_criticidade,"reparo":reparo}
        if ctx.get("causalidade"):causalidade={**causalidade,**ctx["causalidade"]}
        origem,crit,vicio,eleg=classificacoes(sit,causalidade)
        conclusao=("A manifestação alegada não foi constatada na vistoria, dentro do campo, método e limitações registrados." if sit=="NAO_CONSTATADA" else "O elemento examinado apresentou condição conforme no escopo observado." if sit=="CONFORME" else "A manifestação foi observada; a análise causal especializada não foi executada porque o sistema não possui motor causal implementado nesta versão." if sem_motor else "A manifestação foi observada, mas a causalidade permanece inconclusiva." if not causa else "A manifestação e a causa tecnicamente sustentável encontram-se rastreadas nas evidências indicadas.")
        reparo_ok=bool(reparo)
        pat={"id":f"PAT-{idx:03d}","manifestacao":desc,"alegacoes_relacionadas":alg,"ambiente":amb,"localizacao_detalhada":amb,"sistema":sis,"elemento":elem,"constatacao":{"situacao":sit,"descricao":"; ".join(o["descricao_objetiva"] for o in obs),"extensao":None,"metodo":sorted({m for o in obs for m in o["metodo"]}),"evidencias":oids+fot,"fotografias":fot},"constatacoes":oids,"evidencias":oids+fot+med,"medicoes":med,"hipoteses":[h["id"] for h in hips],"analise_causal":{"causa_provavel":causa,"causas_alternativas":[h["causa_candidata"] for h in hips if h["causa_candidata"] and h is not mais],"fundamentos":fundamentos,"limitacoes":ctx.get("evidencias_ausentes",[]),"grau_certeza":"PROVAVEL" if mais and mais["status"]=="MAIS_PROVAVEL" else "POSSIVEL" if causa else "INCONCLUSIVO" if sit in {"ANOMALIA","FALHA"} else "NAO_APLICAVEL"},"mecanismo":mec,"causa":causa,"origem":origem,"criticidade":crit,"vicio_construtivo":{"caracterizado":vicio,"tipo":"INCONCLUSIVO" if vicio or sit in {"ANOMALIA","FALHA"} else "NAO_APLICAVEL","fundamentacao":causalidade.get("fundamentacao_vicio")},"normas_relacionadas":[{"id":n["id"],"item":n.get("item"),"requisito":n.get("requisito"),"verificada":n.get("verificada",False),"aplicabilidade_temporal":n["aplicabilidade_temporal"],"proveniencia":n.get("proveniencia",[]),"aspectos_suportados":n.get("aspectos_suportados",[])} for n in normas],"referencias_tecnicas":[],"ressalvas":ctx.get("evidencias_ausentes",[]),"consequencias":_consequencias(),"reparabilidade":"REPARAVEL" if reparo_ok else "NECESSITA_INVESTIGACAO" if sit in {"ANOMALIA","FALHA"} else "NAO_APLICAVEL","recomendacao":{"necessaria":reparo_ok,"descricao":causalidade.get("reparo") if reparo_ok else None,"extensao":None},"elegibilidade_orcamento":eleg,"orcamento":{"incluir":False,"justificativa":"A composição orçamentária final não integra esta etapa.","quantitativo":None,"unidade":None,"memoria_calculo":None},"conclusao_tecnica":conclusao,"confianca":{"nivel":"MEDIA" if causa else "BAIXA" if sit in {"ANOMALIA","FALHA"} else "ALTA"},"proveniencia":oids or ["vistoria.json"],"redacao":{"analise_alegacoes_causas":None,"consequencias":None,"classificacao":None,"conclusao":None},"texto_tecnico_preliminar":None,"status_validacao":"RASCUNHO"};r["patologias"].append(pat)
    for p in r["patologias"]:
        cap=capacidade_causal(p.get("sistema"));p["analise_causal"]["status_capacidade"]=cap["nivel_de_capacidade"]
        if cap["nivel_de_capacidade"]=="MOTOR_CAUSAL_NAO_IMPLEMENTADO":p["analise_causal"]["limitacoes"]=["MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO",*p["analise_causal"]["limitacoes"]]
        man=next((m for m in r["manifestacoes"] if m["id"].replace("MAN-","PAT-")==p["id"]),{})
        relacionados=selecionar(catalogo,ids=p["evidencias"],sistema=p.get("sistema"),manifestacao=p.get("manifestacao"),contexto={"questoes":man.get("questoes",[]),"sistema":p.get("sistema"),"manifestacao":p.get("manifestacao"),"ambiente":p.get("ambiente"),"elemento":p.get("elemento"),"alegacoes":p.get("alegacoes_relacionadas",[])},relacao_id=p["id"])
        ligados=[e for e in relacionados if e["tipo"]!="NORMA"]+[e for e in catalogo if e["tipo"]=="NORMA" and e.get("sistema") and e.get("sistema")==p.get("sistema")]
        p["evidencias"]=sorted({e["id"] for e in ligados if e["tipo"]!="NORMA"});p["medicoes"]=sorted(e["id"] for e in ligados if e["tipo"]=="MEDICAO")
        p["consequencias"]=avaliar_consequencias(p["constatacao"]["situacao"],ligados)
        p["criticidade"],_=derivar_criticidade(p["constatacao"]["situacao"],p["consequencias"])
        reparo=estruturar_reparo(p.get("causa"),p.get("sistema"),ligados);p["recomendacao"]={"necessaria":bool(reparo),"descricao":reparo,"extensao":reparo.get("escopo") if reparo else None};p["reparabilidade"]="REPARAVEL" if reparo else p["reparabilidade"]
        causal={"causa":p.get("causa"),"origem":p.get("origem"),"evidencias":p.get("analise_causal",{}).get("fundamentos",[]),"criticidade":p["criticidade"],"fundamentacao_criticidade":"Derivada das consequencias estruturadas." if p["criticidade"] not in {"INCONCLUSIVA","NAO_APLICAVEL"} else None,"reparo":reparo}
        p["origem"],p["criticidade"],p["vicio_construtivo"]["caracterizado"],p["elegibilidade_orcamento"]=classificacoes(p["constatacao"]["situacao"],causal)
        p["vicio_construtivo"]["tipo"]=tipo_vicio(ligados,p["vicio_construtivo"]["caracterizado"])
        hip=next((h for h in r["hipoteses"] if h["id"] in p["hipoteses"] and h.get("causa_candidata")==p.get("causa")),None);p["analise_causal"]["aspectos_requeridos"]=(hip or {}).get("aspectos_requeridos",[])
        p["analise_causal"]["aspectos_origem"]={"ENDOGENA_CONSTRUTIVA":["DETALHE_CONSTRUTIVO_DOCUMENTADO","EXECUCAO_DIVERGENTE_DOCUMENTADA"],"EXOGENA":["IMPACTO_REGISTRADO","INTERVENCAO_TERCEIRO_DOCUMENTADA"],"FUNCIONAL":["COMPORTAMENTO_FUNCIONAL_OBSERVADO"],"USO_OPERACAO_MANUTENCAO":["MANUTENCAO_AUSENTE_DOCUMENTADA","USO_INADEQUADO_DOCUMENTADO"]}.get(p["origem"],[])
        p["vicio_construtivo"]["fundamentacao"]="Causa e origem sustentadas pelas evidências primárias indicadas." if p["vicio_construtivo"]["caracterizado"] else p["vicio_construtivo"]["fundamentacao"]
        p["vicio_construtivo"]["revisao_profissional"]={"status":"NAO_REVISADO"}
        p["orcamento"]["revisao_profissional"]={"status":"NAO_REVISADO"}
        for n in p["normas_relacionadas"]:
            fonte=next((x for x in conhecimento.get("normas",[]) if x.get("id")==n["id"]),{})
            n.update({"edicao":fonte.get("edicao"),"pagina":fonte.get("pagina"),"tipo_requisito":fonte.get("tipo_requisito"),"metodo_verificacao":fonte.get("metodo_verificacao"),"criterio":fonte.get("criterio"),"confianca":fonte.get("confianca",{"nivel":"MEDIA" if n["verificada"] else "BAIXA"}),"avaliacao_conformidade":avaliar_conformidade_normativa(fonte,ligados)})
    for qt in delimitacao["questoes_tecnicas"]:
        pats=[p for p in r["patologias"] if qt["id"] in next(m["questoes"] for m in r["manifestacoes"] if m["id"]==f"MAN-{int(p['id'][-3:]):03d}")]
        dimensoes=intencoes(qt.get("descricao",""));exige_causa=bool({"CAUSALIDADE","ORIGEM","MECANISMO"}&set(dimensoes)) and "JURIDICO" not in dimensoes;sem_capacidade=any(p.get("analise_causal",{}).get("status_capacidade")=="MOTOR_CAUSAL_NAO_IMPLEMENTADO" for p in pats)
        inc=any(p["constatacao"]["situacao"]=="INCONCLUSIVA" or (p["constatacao"]["situacao"]=="ANOMALIA" and not p["causa"]) for p in pats) and exige_causa
        st="SANEADA_COM_RESSALVA" if pats and inc else "SANEADA" if pats else "PREJUDICADA"
        if exige_causa and sem_capacidade:st="INCONCLUSIVA_POR_LIMITACAO";conclusao="MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO: a constatação pode ser descrita, mas a causa não foi analisada por módulo causal específico.";ressalvas=["Limitação de capacidade do software; não equivale a inconclusão técnica por insuficiência de evidência."]
        else:conclusao="Questão tratada pelas evidências indicadas." if pats else "Não há evidência de campo vinculada.";ressalvas=["Causalidade inconclusiva"] if inc else []
        r["questoes_saneadas"].append({"id":qt["id"],"status":st,"patologias":[p["id"] for p in pats],"observacoes":sorted({x for p in pats for x in p["constatacoes"]}),"fotografias":sorted({x for p in pats for x in p["constatacao"]["fotografias"]}),"medicoes":sorted({x for p in pats for x in p["medicoes"]}),"hipoteses":sorted({x for p in pats for x in p["hipoteses"]}),"normas":[],"conclusao":conclusao,"ressalvas":ressalvas,"quesitos":qt.get("quesitos_relacionados",[]),"confianca":{"nivel":"MEDIA" if pats else "BAIXA"}})
        r["questoes_saneadas"][-1]["dimensoes_saneamento"]=[{"intencao":d,"status":"NAO_SANEADA_POR_CAPACIDADE" if d in {"CAUSALIDADE","ORIGEM","MECANISMO"} and sem_capacidade else "SANEADA" if pats else "PREJUDICADA"} for d in (dimensoes or ["CARACTERIZACAO"])]
    porqt={q["id"]:q for q in r["questoes_saneadas"]}
    for c in r["cobertura_quesitos"]:
        qs=[porqt[x] for x in c["questoes"] if x in porqt];c["patologias"]=sorted({x for q in qs for x in q["patologias"]});c["observacoes"]=sorted({x for q in qs for x in q["observacoes"]});c["fotografias"]=sorted({x for q in qs for x in q["fotografias"]});c["medicoes"]=sorted({x for q in qs for x in q["medicoes"]});c["hipoteses"]=sorted({x for q in qs for x in q["hipoteses"]});c["status"]="RESPONDIVEL_COM_RESSALVA" if qs and all(q["status"]!="PREJUDICADA" for q in qs) else c["status"]
    r["autoauditoria"]=auditar(r,vistoria);r["gate_redacao"]="BLOQUEADO_PARA_REDACAO";r["autonomia"].update({"decisoes_autonomas":len(r["patologias"])+len(r["questoes_saneadas"]),"hipoteses_criadas":len(r["hipoteses"]),"hipoteses_testadas":len(r["hipoteses"]),"hipoteses_fortalecidas":sum(h["status"] in {"FORTALECIDA","MAIS_PROVAVEL"} for h in r["hipoteses"]),"hipoteses_afastadas":sum(h["status"] in {"ENFRAQUECIDA","AFASTADA"} for h in r["hipoteses"]),"ressalvas_criadas":sum(bool(p["ressalvas"]) for p in r["patologias"]),"normas_recuperadas":sum(len(p["normas_relacionadas"]) for p in r["patologias"])});return r

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("diretorio",type=Path);p.add_argument("--contexto",type=Path)
    a=p.parse_args();d=a.diretorio;load=lambda n:json.loads((d/n).read_text(encoding="utf-8"));ctx=json.loads(a.contexto.read_text(encoding="utf-8")) if a.contexto else None;obj=executar(load("processo.json"),load("delimitacao-pericial.json"),load("plano-vistoria.json"),load("vistoria.json"),ctx);out=d/"analise-motor-vicios.json";out.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n");print(out);return 0
if __name__=="__main__":raise SystemExit(main())

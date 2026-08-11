"""Orquestrador produtivo do Motor Técnico de Vícios Construtivos."""
from __future__ import annotations
import uuid
from copy import deepcopy
from scripts.auditoria_pericial import auditar_claim,auditar_proposicoes,executar_deep_audit,executar_detector,extrair_claims,registrar_trilha
from .autocorrigir import autocorrigir
from .motor import executar
from .validar_motor import validar
from .auditar import auditar,classificar_autoauditoria
from .regras_probatorias import identidade_fontes

REPROVADOS={"INSUFFICIENT","UNSUBSTANTIATED","INTERPOLATED","CONTRADICTED"}
def recalcular_gate(estado,status_declarado=None):
    materiais=estado.get("materiais",[])
    deep=estado.get("deep",[])
    bloqueio=bool(estado.get("erros") or estado.get("detector") or estado.get("proposition_bloqueante") or estado.get("medicao_ausente") or any(a.get("severidade") in {"CRITICO","CRÍTICO"} for a in deep) or any(a.get("veredito") in REPROVADOS|{"UNVERIFIABLE"} for a in materiais) or any(a.get("bloqueante") for a in estado.get("autoauditoria",[])))
    importante=any(a.get("severidade")=="IMPORTANTE" for a in deep)
    return "BLOQUEADO_PARA_REDACAO" if bloqueio else "APTO_PARA_REDACAO_COM_RESSALVAS" if estado.get("ressalvas") or importante else "APTO_PARA_REDACAO"
def _catalogo_com_inferencias(resultado):
    # HIP, PAT e QT são nós intermediários do grafo, nunca folhas probatórias.
    return [deepcopy(e) for e in resultado.get("catalogo_evidencias",[]) if e.get("classe_probatoria")=="EVIDENCIA_PRIMARIA"]

def _decisoes_trilha(resultado,auditorias):
    decisoes=[{"decisao":"Gate pos-auditoria","evidencia":str(len(auditorias)),"justificativa":"Somente o estado final validado controla a liberacao"}]
    for relacao in resultado.get("relacoes_associacao",[]):
        decisoes.append({"decisao":"Associacao DOC/ENS-MAN/PAT","evidencia":relacao["evidencia_id"],"justificativa":f'{relacao["status"]}; motivos={",".join(relacao["motivos"])}; alvos={",".join(relacao["manifestacoes"])}'})
    return decisoes

def _fontes_trilha(catalogo):
    return sorted({fonte for evidencia in catalogo for fonte in identidade_fontes(evidencia)})

def _relacoes(claim,resultado,catalogo):
    pat=next((p for p in resultado.get("patologias",[]) if p["id"]==claim.get("patologia")),None);ids=set()
    if claim.get("evidencia_id"):ids.add(claim["evidencia_id"])
    if pat:ids.update(pat.get("evidencias",[]));ids.update(n["id"] for n in pat.get("normas_relacionadas",[]))
    if claim.get("questao"):
        qt=next((q for q in resultado.get("questoes_saneadas",[]) if q["id"]==claim["questao"]),None)
        for pid in (qt or {}).get("patologias",[]):
            ligado=next((p for p in resultado.get("patologias",[]) if p["id"]==pid),None)
            if ligado:ids.update(ligado.get("evidencias",[]));ids.update(n["id"] for n in ligado.get("normas_relacionadas",[]))
    return [e for e in catalogo if e["id"] in ids]

def _auditar(resultado,processo,delimitacao,vistoria,conhecimento):
    catalogo=_catalogo_com_inferencias(resultado);claims=extrair_claims(resultado);auditorias=[]
    for claim in claims:
        rel=_relacoes(claim,resultado,catalogo);auditorias.append(auditar_claim(claim,rel,catalogo))
    detector=executar_detector(resultado,processo=processo,delimitacao=delimitacao,vistoria=vistoria,normas=conhecimento.get("normas",[]),ressalvas=delimitacao.get("ressalvas",[]));deep=executar_deep_audit(auditorias,resultado)
    return claims,auditorias,detector,deep,catalogo

def executar_pipeline_motor(processo,delimitacao,plano,vistoria,conhecimento=None,*,execucao_id=None):
    conhecimento=conhecimento or {};pesquisa=None
    if not conhecimento.get("normas") and conhecimento.get("search_provider"):
        from scripts.conhecimento_privado.pesquisa_online import EgressPolicy,buscar_seguro,dados_sensiveis_processo
        pesquisa=buscar_seguro("fonte oficial pública aplicável à questão técnica",conhecimento["search_provider"],EgressPolicy(permitir_egress=True,dados_sensiveis=dados_sensiveis_processo(processo)))
    inicial=executar(processo,delimitacao,plano,vistoria,conhecimento=conhecimento)
    if pesquisa:inicial["pesquisa_online"]={"status":pesquisa["status"],"pesquisas_realizadas":1,"fontes_oficiais_localizadas":[x.get("url") for x in pesquisa["resultados"] if x.get("oficial")],"fontes_rejeitadas":[x.get("url") for x in pesquisa["resultados"] if not x.get("oficial")],"fontes_cacheadas":[],"revalidacoes_vigencia":0,"pesquisas_desnecessarias_evitadas":0}
    if inicial["status_execucao"]!="ANALISE_INICIAL":
        trilha=registrar_trilha(execucao_id=execucao_id or str(uuid.uuid4()),processo=processo.get("numero_processo"),skill="motor-vicios-construtivos",objetivo="Processar evidências de vistoria",inputs=["processo","delimitacao","plano","vistoria"],outputs=["analise_final"],status="BLOQUEADO",proveniencia=inicial.get("proveniencia",[]));return {"analise_inicial":inicial,"analise_final":inicial,"claims":[],"grounding":[],"detector":[],"deep_audit":[],"proposition_audit_results":[],"autocorrecoes":[],"trilha":trilha,"gate":"BLOQUEADO_PARA_REDACAO"}
    erros_iniciais=validar(inicial,processo,delimitacao,plano,vistoria,conhecimento.get("normas",[]),delimitacao.get("ressalvas",[]));claims,audits,detector,deep,catalogo=_auditar(inicial,processo,delimitacao,vistoria,conhecimento)
    final,correcoes=autocorrigir(inicial,claims,audits,detector+deep);final["autoauditoria"]=auditar(final,vistoria);resultado_autoauditoria=classificar_autoauditoria(final["autoauditoria"])
    claims_f,audits_f,detector_f,deep_f,catalogo_f=_auditar(final,processo,delimitacao,vistoria,conhecimento);final["catalogo_evidencias"]=catalogo_f
    erros_finais=validar(final,processo,delimitacao,plano,vistoria,conhecimento.get("normas",[]),delimitacao.get("ressalvas",[]));materiais=[a for a in audits_f if a["saliencia"]=="LOAD_BEARING"]
    proposition=auditar_proposicoes(claims_f,audits_f,catalogo_f);prop_bloqueante=any(p["verdict"]!="SUPPORTED" for p in proposition)
    from scripts.planejamento_pericial.validar_plano import recalcular_execucao
    execucao_cobertura=recalcular_execucao(plano,vistoria)
    medicao_indispensavel_ausente=not execucao_cobertura["apto"]
    ressalvas=any(p.get("ressalvas") or p.get("analise_causal",{}).get("grau_certeza")=="INCONCLUSIVO" for p in final.get("patologias",[]))
    gate=recalcular_gate({"erros":erros_finais,"detector":detector_f,"deep":deep_f,"proposition_bloqueante":prop_bloqueante,"medicao_ausente":medicao_indispensavel_ausente,"materiais":materiais,"autoauditoria":final["autoauditoria"],"ressalvas":ressalvas},status_declarado=final.get("gate_redacao"));final["gate_redacao"]=gate
    final["autonomia"].update({"claims_geradas":len(claims),"claims_grounded":sum(a["veredito"]=="GROUNDED" for a in audits_f),"claims_insufficient":sum(a["veredito"] in {"INSUFFICIENT","UNSUBSTANTIATED","UNVERIFIABLE"} for a in audits),"claims_interpolated":sum(a["veredito"]=="INTERPOLATED" for a in audits),"claims_reduzidas":len(correcoes),"claims_removidas":sum(c["acao"].startswith("REMOVER") for c in correcoes),"autocorrecoes":len(correcoes),"normas_utilizadas":sum(len(p.get("normas_relacionadas",[])) for p in final.get("patologias",[])),"normas_rejeitadas":sum(n.get("aplicabilidade_temporal")=="NAO_APLICAVEL" for p in final.get("patologias",[]) for n in p.get("normas_relacionadas",[])),"fontes_online":len(final.get("pesquisa_online",{}).get("fontes_oficiais_localizadas",[])),"perguntas_perito":len(final["autonomia"].get("perguntas_necessarias",[]))})
    trilha=registrar_trilha(execucao_id=execucao_id or str(uuid.uuid4()),processo=processo.get("numero_processo"),skill="motor-vicios-construtivos",objetivo="Gerar, auditar, corrigir e liberar análise técnica",inputs=["processo","delimitacao","plano","vistoria","conhecimento"],fontes=_fontes_trilha(catalogo_f),artefatos=["PAT_INICIAL","PAT_FINAL"],decisoes_autonomas=_decisoes_trilha(final,audits_f),outputs=["analise_final"],auditorias=[a["claim_id"]+":"+a["veredito"] for a in audits_f]+[p["claim_id"]+":PROPOSITION:"+p["verdict"] for p in proposition],achados=[{"tipo":a.get("tipo"),"severidade":a.get("severidade")} for a in detector_f+deep_f],correcoes=correcoes,status="BLOQUEADO" if gate=="BLOQUEADO_PARA_REDACAO" else "APROVADO",proveniencia=final.get("proveniencia",[]))
    return {"analise_inicial":inicial,"erros_iniciais":erros_iniciais,"claims":claims,"grounding_inicial":audits,"detector_inicial":detector,"deep_audit_inicial":deep,"autocorrecoes":correcoes,"analise_final":final,"claims_finais":claims_f,"grounding_final":audits_f,"detector_final":detector_f,"deep_audit_final":deep_f,"erros_finais":erros_finais,"coverage_execucao":execucao_cobertura,
            "coverage_inputs":{"plano":{k:deepcopy(plano.get(k,[])) for k in ("requisitos_cobertura","atividades","fotografias","medicoes","ensaios","documentos_a_solicitar")},"vistoria":{k:deepcopy(vistoria.get(k,[])) for k in ("cobertura","atividades_executadas","fotografias","medicoes","ensaios","documentos_obtidos","observacoes","declaracoes")}},
            "proposition_audit":{"modo":"WRAPPER_LOCAL","resultados":proposition},"claim_audit":{"modo":"INTEGRACAO_METODOLOGICA_ADAPTADA","resultados":audits_f},"proposition_audit_results":proposition,"autoauditoria_resultado":resultado_autoauditoria,"trilha":trilha,"gate":gate}

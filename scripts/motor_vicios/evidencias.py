"""Extrai, audita e associa fatos observáveis sem antecipar inferências técnicas."""
from __future__ import annotations
import re
import unicodedata
from copy import deepcopy

INFERENCIAS_PROIBIDAS={"CAUSA","ORIGEM","VICIO_CONSTRUTIVO","CONFORMIDADE_NORMATIVA","REPARO_DEFINIDO","ORCAMENTO","CRITICIDADE"}

def normalizar(valor):
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKD",str(valor or "")).encode("ascii","ignore").decode().lower()).strip()

def _texto(*partes):return " ".join(str(x) for x in partes if x not in (None,""))

PADROES_OBSERVAVEIS={
 "INTERFACE_IDENTIFICADA":(r"\binterface\b",r"\bjunta\b",r"\bencontro entre\b"),
 "VEDACAO_DETERIORADA":(r"vedacao deteriorada",r"selagem da junta (?:encontra-se )?(?:degradada|deteriorada)",r"material de fechamento da interface apresenta perda de integridade",r"selante (?:degradado|deteriorado)"),
 "VEDACAO_INTEGRA":(r"vedacao (?:aparenta )?integra",r"selagem (?:preservada|integra)",r"selante integro"),
 "MANCHA_VISIVEL":(r"\bmancha\b",),"UMIDADE_MEDIDA":(r"teor de umidade",r"umidade medid"),
 "PRECIPITACAO_REGISTRADA":(r"\bchuva\b",r"precipitacao"),"VAZAMENTO_OBSERVADO":(r"\bvazamento\b",r"pressurizacao positiva"),
 "AUSENCIA_VAZAMENTO_NO_ENSAIO":(r"sem vazamento",r"estanqueidade negativa"),
 "IMPACTO_REGISTRADO":(r"impacto posterior",r"avaria por impacto"),"INTERVENCAO_TERCEIRO_DOCUMENTADA":(r"obra de terceiro",r"intervencao externa"),
 "USO_INADEQUADO_DOCUMENTADO":(r"uso inadequado",r"operacao inadequada",r"intervencao do usuario"),
 "MANUTENCAO_AUSENTE_DOCUMENTADA":(r"ausencia de manutencao",r"sem manutencao",r"manutencao inadequada"),
 "COMPORTAMENTO_FUNCIONAL_OBSERVADO":(r"fenomeno inerente",r"comportamento funcional",r"funcionamento normal"),
 "DETALHE_CONSTRUTIVO_DOCUMENTADO":(r"detalhe executivo",r"projeto especifica",r"memorial especifica"),
 "EXECUCAO_DIVERGENTE_DOCUMENTADA":(r"execucao divergente",r"nao executado conforme",r"solucao executada difere"),
 "RISCO_SEGURANCA_REGISTRADO":(r"risco de colapso",r"instabilidade",r"risco (?:grave )?de seguranca"),
 "RISCO_SALUBRIDADE_REGISTRADO":(r"risco a saude",r"insalubridade registrada"),
 "PERDA_FUNCIONAL_REGISTRADA":(r"perda (?:de )?funcionalidade",r"perda funcional",r"prejuizo funcional",r"perda de desempenho"),
 "DEGRADACAO_RELEVANTE_REGISTRADA":(r"degradacao relevante",),"REPERCUSSAO_LOCALIZADA_REGISTRADA":(r"anomalia localizada",r"repercussao limitada"),
 "EVOLUCAO_REGISTRADA":(r"evolucao registrada",r"progressao medida"),"EXTENSAO_REGISTRADA":(r"extensao medida",r"area afetada"),
 "APARENTE_EM_INSPECAO":(r"visivel em inspecao ordinaria",r"defeito aparente"),"NAO_APARENTE_EM_INSPECAO":(r"nao identificavel por inspecao ordinaria",r"defeito oculto"),
 "FISSURA_PRESENTE":(r"\bfissura\b",),"INFILTRACAO_ATIVA":(r"\binfiltracao(?: ativa)?\b",),
 "TRINCA_PRESENTE":(r"\btrinca\b",),"DEFORMACAO_PRESENTE":(r"\bdeformacao\b",),"UMIDADE_OBSERVADA":(r"\bumidade\b",),"ESCORRIMENTO_VISIVEL":(r"\bescorrimento\b",),"DEGRAU_PRESENTE":(r"\bdegrau\b",),
 "CORROSAO_APARENTE":(r"\bcorrosao\b",),"AUSENCIA_DEGRAU":(r"ausencia de degrau",r"sem degrau"),
 "CAUSA_INCONCLUSIVA":(r"\bcausa\b",),
 "PROJETO_CONSTRUTIVO_DOCUMENTADO":(r"projeto (?:executivo|construtivo)",),"MATERIAL_CONSTRUTIVO_DOCUMENTADO":(r"material especificado",r"material empregado"),
 "ESPECIFICACAO_CONSTRUTIVA_DOCUMENTADA":(r"especificacao construtiva",),"PROCEDIMENTO_EXECUTIVO_DOCUMENTADO":(r"procedimento executivo",),
 "CONTROLE_TECNOLOGICO_DOCUMENTADO":(r"controle tecnologico",),"DOCUMENTACAO_OBRA_VERIFICADA":(r"documentacao de obra",),
 "NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA":(r"execucao divergente",r"resultado incompatível com o requisito",r"resultado incompativel com o requisito"),
}

ASPECTOS_NORMATIVOS={"REQUISITO_NORMATIVO_VERIFICADO","METODO_NORMATIVO_VERIFICADO","CRITERIO_NORMATIVO_VERIFICADO","DEFINICAO_NORMATIVA_VERIFICADA","ESCOPO_NORMATIVO_VERIFICADO","APLICABILIDADE_TEMPORAL"}

NEGADORES=(r"\bnao\s+(?:foi|foram)?\s*(?:observad[oa]s?|identificad[oa]s?|constatad[oa]s?)\b(?:\s+indicios?\s+de)?",r"\bnao\s+(?:ha|houve|apresenta)\b",r"\bsem\s+(?:sinais?|indicios?)?\s*(?:de\s+)?",r"\bausencia\s+de\s+")
HIPOTESES=(r"nao se (?:pode )?descarta",r"nao se descarta",r"nao e possivel descartar")
INCERTEZAS=(r"nao foi possivel determinar",r"nao foi possivel identificar")
ASPECTOS_DE_AUSENCIA_OU_DIVERGENCIA={"AUSENCIA_DEGRAU","AUSENCIA_VAZAMENTO_NO_ENSAIO","MANUTENCAO_AUSENTE_DOCUMENTADA","USO_INADEQUADO_DOCUMENTADO","NAO_APARENTE_EM_INSPECAO","EXECUCAO_DIVERGENTE_DOCUMENTADA","NAO_CONFORMIDADE_CONSTRUTIVA_VERIFICADA"}

def _segmentos(texto):
    independentes=r"(?:existe|ha|apresenta|foi\s+(?:observad[oa]|constatad[oa]|identificad[oa])|verificou-se|nao\s+(?:ha|houve|apresenta|foi))"
    return [x.strip() for x in re.split(rf"\bmas\b|\bporem\b|\bcontudo\b|\bentretanto\b|;|\be\s+(?={independentes}\b)",texto) if x.strip()]

def _polaridade(segmento,achado,aspecto):
    if aspecto in ASPECTOS_DE_AUSENCIA_OU_DIVERGENCIA:return "AFIRMADO"
    if any(re.search(p,segmento) for p in HIPOTESES):return "HIPOTETICO"
    if any(re.search(p,segmento) for p in INCERTEZAS):return "INCERTO"
    inicio=max(0,achado.start()-80);prefixo=segmento[inicio:achado.start()]
    return "NEGADO" if any(re.search(p,prefixo) for p in NEGADORES) else "AFIRMADO"

def extrair_aspectos(evidencia):
    """Retorna candidatos estritamente observáveis e suas âncoras textuais."""
    texto=normalizar(_texto(evidencia.get("descricao"),evidencia.get("resultado"),evidencia.get("grandeza"),evidencia.get("anotacao")))
    candidatos=[]
    basicos={"OBSERVACAO":"CONSTATACAO_DE_VISTORIA","MEDICAO":"MEDICAO_REGISTRADA","FOTOGRAFIA":"REGISTRO_VISUAL_INTERPRETADO","DOCUMENTO":"CONTEUDO_DOCUMENTAL","ENSAIO":"RESULTADO_ENSAIO","NORMA":"REQUISITO_NORMATIVO_VERIFICADO"}
    tipo=evidencia.get("tipo")
    if tipo=="FOTOGRAFIA" and evidencia.get("estado_interpretacao")!="INTERPRETADA":return []
    if tipo=="NORMA" and not evidencia.get("acessivel"):return []
    if tipo in basicos:
        ancora=next((normalizar(evidencia.get(k)) for k in ("descricao","anotacao","resultado","valor","requisito") if evidencia.get(k) not in (None,"")),"")
        candidatos.append({"aspecto":basicos[tipo],"ancora":ancora,"trecho_fonte":texto or tipo,"polaridade":"AFIRMADO","localizacao":evidencia.get("local")})
    if tipo=="NORMA":
        for campo,aspecto in (("metodo_verificacao","METODO_NORMATIVO_VERIFICADO"),("criterio","CRITERIO_NORMATIVO_VERIFICADO"),("definicao","DEFINICAO_NORMATIVA_VERIFICADA"),("escopo","ESCOPO_NORMATIVO_VERIFICADO"),("aplicabilidade_temporal","APLICABILIDADE_TEMPORAL")):
            if evidencia.get(campo) not in (None,"",{},[]):candidatos.append({"aspecto":aspecto,"ancora":normalizar(evidencia[campo]),"trecho_fonte":texto or tipo,"polaridade":"AFIRMADO","localizacao":None})
        return candidatos
    for segmento in _segmentos(texto):
      for aspecto,padroes in PADROES_OBSERVAVEIS.items():
        achado=next((m for p in padroes if (m:=re.search(p,segmento))),None)
        if achado:candidatos.append({"aspecto":aspecto,"ancora":achado.group(0),"trecho_fonte":segmento,"polaridade":_polaridade(segmento,achado,aspecto),"localizacao":"PAREDE" if "parede" in segmento else "TETO" if "teto" in segmento else evidencia.get("local")})
    if "VEDACAO_INTEGRA" in {x["aspecto"] for x in candidatos}:
        candidatos=[x for x in candidatos if x["aspecto"]!="VEDACAO_DETERIORADA"]
    return candidatos

def proposicoes_observacionais(texto):
    """Expõe a mesma polaridade da extração para a ingestão natural da vistoria."""
    evidencia={"id":"OBS-CANDIDATA","tipo":"OBSERVACAO","descricao":texto,"resultado":None,"local":None}
    fisicos={"FISSURA_PRESENTE":"fissura","TRINCA_PRESENTE":"trinca","INFILTRACAO_ATIVA":"infiltração ativa","UMIDADE_OBSERVADA":"umidade"}
    return [{**c,"manifestacao":fisicos[c["aspecto"]]} for c in extrair_aspectos(evidencia) if c["aspecto"] in fisicos]

def auditar_aspectos(evidencia):
    """Camada Claim Audit adaptada: candidato deve ter fidelidade literal e delta positivo."""
    from scripts.auditoria_pericial.grounding import auditar_candidato_aspecto
    candidatos=extrair_aspectos(evidencia);saida=[]
    for c in candidatos:
        audit=auditar_candidato_aspecto(evidencia,c);saida.append({"id":f"ASP-{evidencia['id']}-{len(saida)+1:02d}","evidencia":evidencia["id"],"aspecto":c["aspecto"],"natureza":"FATO_OBSERVAVEL","polaridade":c["polaridade"],"localizacao":c.get("localizacao"),"fidelidade":audit["fidelidade"],"delta_informacional":audit["delta_informacional"],"veredito":audit["veredito"],"ancora":c["ancora"],"trecho_fonte":c["trecho_fonte"],"aspectos_derivados_consultados":audit["aspectos_derivados_consultados"],"modo":"INTEGRACAO_METODOLOGICA_ADAPTADA"})
    return saida

def _base(item,tipo,origem,descricao):
    e={"id":item["id"],"tipo":tipo,"origem":origem,"descricao":descricao,"resultado":item.get("resultado"),"valor":item.get("valor"),"unidade":item.get("unidade"),"grandeza":item.get("grandeza"),"anotacao":item.get("anotacao"),"aspectos_contraditos":[],"local":item.get("ambiente") or item.get("local"),"trecho":item.get("trecho"),"elemento":item.get("elemento"),"data":item.get("data_hora"),"sistema":item.get("sistema"),"manifestacao":item.get("manifestacao"),"atividade":item.get("atividade") or item.get("atividade_planejada"),"questoes":item.get("questoes",[]),"quesitos":item.get("quesitos",[]),"alegacoes":item.get("alegacoes",[]),"proveniencia":item.get("proveniencia",[]),"confianca":item.get("confianca",{}),"acessivel":True,"estado_interpretacao":item.get("estado_interpretacao")}
    e["finalidade_planejada"]=item.get("finalidade_planejada")
    for campo in ("entidade","dominio","url","documento","status_verificacao","classificacao_fonte","dominio_oficial","escopo_fonte","conteudo_consultado","conteudo_normativo_verificado","item","requisito","titulo","edicao","metodo_verificacao","criterio","definicao","escopo","aplicabilidade_temporal"):
        e[campo]=item.get(campo)
    e["auditoria_aspectos"]=auditar_aspectos(e);e["aspectos_suportados"]=[a["aspecto"] for a in e["auditoria_aspectos"] if a["veredito"]=="GROUNDED" and a["polaridade"]=="AFIRMADO"];e["aspectos_contraditos"]=[a["aspecto"] for a in e["auditoria_aspectos"] if a["polaridade"]=="NEGADO"];e["classe_probatoria"]="EVIDENCIA_PRIMARIA";return e

def construir_catalogo(vistoria,documentos=None,normas=None):
    catalogo=[]
    for obs in vistoria.get("observacoes",[]):catalogo.append(_base(obs,"OBSERVACAO","VISTORIA",obs.get("descricao_objetiva")))
    for med in vistoria.get("medicoes",[]):catalogo.append(_base(med,"MEDICAO","VISTORIA",_texto(med.get("anotacao"),med.get("grandeza"),med.get("valor"),med.get("unidade"))))
    for fot in vistoria.get("fotografias",[]):
        item=dict(fot);item["estado_interpretacao"]="INTERPRETADA" if fot.get("descricao_visual_observada") else "NAO_INTERPRETADA";catalogo.append(_base(item,"FOTOGRAFIA","VISTORIA",fot.get("descricao_visual_observada")))
    for ens in vistoria.get("ensaios",[]):catalogo.append(_base(ens,"ENSAIO","VISTORIA",_texto(ens.get("nome"),ens.get("resultado"))))
    for dec in vistoria.get("declaracoes",[]):
        e=_base(dec,"RESSALVA",dec.get("natureza"),dec.get("texto_original"));e["classe_probatoria"]="INFERENCIA_INTERMEDIARIA";e["aspectos_suportados"]=["DECLARACAO"];catalogo.append(e)
    for doc in documentos or vistoria.get("documentos_obtidos",[]):catalogo.append(_base(doc,"DOCUMENTO","DOCUMENTO",doc.get("descricao") or doc.get("titulo")))
    for nor in normas or []:
        from .normas import normalizar_fonte_normativa
        item=normalizar_fonte_normativa(nor,nor.get("data_relevante"));item["acessivel"]=bool(item.get("verificada") and item.get("proveniencia") and item.get("requisito"));e=_base(item,"NORMA","NORMA_TECNICA",item.get("requisito") or item.get("titulo"));e["acessivel"]=item["acessivel"];e["auditoria_aspectos"]=auditar_aspectos(e);e["aspectos_suportados"]=[a["aspecto"] for a in e["auditoria_aspectos"]];e["classe_probatoria"]="EVIDENCIA_PRIMARIA" if e["acessivel"] else "INFERENCIA_INTERMEDIARIA";catalogo.append(e)
    return catalogo

def pontuar_associacao(evidencia,contexto):
    """Associa DOC/ENSAIO apenas por chaves convergentes; ausência não é wildcard."""
    campos=(("questoes",3),("atividade",3),("alegacoes",2),("ambiente",2),("sistema",3),("elemento",2),("manifestacao",2))
    pontos=0;motivos=[]
    for campo,peso in campos:
        a=evidencia.get(campo);b=contexto.get(campo)
        if isinstance(a,list) or isinstance(b,list):ok=bool(set(a or [])&set(b or []))
        else:ok=bool(a and b and normalizar(a)==normalizar(b))
        if ok:pontos+=peso;motivos.append(campo)
    confianca="ALTA" if pontos>=5 else "MEDIA" if pontos>=3 else "BAIXA"
    return {"score":pontos,"confianca":confianca,"motivo":motivos,"status":"ASSOCIADA" if confianca=="ALTA" else "REVISAO_NECESSARIA" if confianca=="MEDIA" else "PENDENTE_ASSOCIACAO"}

def associar_documentos_ensaios(catalogo,contextos):
    """Resolve DOC/ENS contra todas as MAN antes do uso; empate nunca associa."""
    relacoes=[]
    for evidencia in (e for e in catalogo if e["tipo"] in {"DOCUMENTO","ENSAIO"}):
        candidatos=[(ctx,pontuar_associacao(evidencia,ctx)) for ctx in contextos]
        altos=[x for x in candidatos if x[1]["confianca"]=="ALTA"]
        maior=max((a[1]["score"] for a in altos),default=-1)
        vencedores=[a for a in altos if a[1]["score"]==maior]
        if len(vencedores)==1:
            ctx,assoc=vencedores[0];status="ASSOCIADA"
            alvos=[ctx["relacao_id"]]
        else:
            assoc={"score":maior,"confianca":"BAIXA","motivo":sorted({m for _,a in vencedores for m in a["motivo"]})};status="AMBIGUA" if len(vencedores)>1 else "NAO_ASSOCIADA"
            alvos=sorted(ctx["relacao_id"] for ctx,_ in vencedores)
        relacoes.append({"evidencia_id":evidencia["id"],"tipo_evidencia":evidencia["tipo"],"manifestacoes":alvos,"patologias":[x.replace("MAN-","PAT-") for x in alvos],"status":status,"confianca":assoc["confianca"],"score":assoc["score"],"motivos":assoc["motivo"]})
    return relacoes

def consolidar_aspectos(catalogo):
    """Mantém contexto espacial/temporal e explicita contradição no mesmo trecho."""
    grupos={}
    for e in catalogo:
        chave=(e.get("local"),e.get("trecho"),e.get("elemento"),e.get("data"));grupos.setdefault(chave,[]).append(e)
    saida=[]
    for chave,evidencias in grupos.items():
        aspectos={a for e in evidencias for a in e.get("aspectos_suportados",[])};contradicao={"VEDACAO_DETERIORADA","VEDACAO_INTEGRA"}<=aspectos
        saida.append({"contexto":chave,"aspectos":sorted(aspectos),"status":"CONTRADICTED" if contradicao else "GROUNDED","evidencias":[e["id"] for e in evidencias]})
    return saida

def selecionar(catalogo, *, ids=None, sistema=None, manifestacao=None,contexto=None,relacao_id=None,relacoes=None):
    ids=set(ids or []);contexto=contexto or {"sistema":sistema,"manifestacao":manifestacao}
    saida=[]
    for e in catalogo:
        if e["id"] in ids and e["tipo"] not in {"DOCUMENTO","ENSAIO"}:saida.append(deepcopy(e));continue
        if e["tipo"] in {"DOCUMENTO","ENSAIO"}:
            validada=next((r for r in (relacoes or []) if r["evidencia_id"]==e["id"] and r["status"]=="ASSOCIADA" and relacao_id in r["manifestacoes"]),None)
            assoc=pontuar_associacao(e,contexto)
            if relacoes is not None and not validada:continue
            if assoc["confianca"]=="ALTA":
                relacionado=deepcopy(e)
                relacionado["relacao_associacao"]={"relacao_id":relacao_id,"evidencia_id":e["id"],**assoc,"validacao_global":bool(validada)}
                saida.append(relacionado)
        elif e["tipo"]=="NORMA" and e.get("sistema") and sistema and e["sistema"]==sistema:saida.append(deepcopy(e))
    return sorted(saida,key=lambda item:item["id"])

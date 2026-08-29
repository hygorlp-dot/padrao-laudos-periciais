"""Pipeline judicial: plano, redação, grounding, auditorias, correção e gate."""

from __future__ import annotations
from .planejar_redacao import planejar
from .redigir import redigir
from .auditar_estilo import auditar_estilo, auditar_redundancia_estrutural
from .auditar_fidelidade import auditar_fidelidade, auditar_grounding_redacao, auditar_laudo_semantico
from .autocorrigir_redacao import autocorrigir

REPROVADOS = {"INSUFFICIENT", "UNSUBSTANTIATED", "INTERPOLATED", "UNVERIFIABLE", "CONTRADICTED"}

def recalcular_gate_redacao(*,fidelidade,semanticos,ausentes,materiais,tem_ressalva=False):
    bloqueio=bool(fidelidade or semanticos or ausentes or any(a.get("veredito") in REPROVADOS for a in materiais))
    return "BLOQUEADO_PARA_LAUDO" if bloqueio else "APTO_PARA_LAUDO_COM_RESSALVAS" if tem_ressalva else "APTO_PARA_LAUDO"


def _texto(valor):
    return valor.get("texto") if isinstance(valor, dict) else valor


def _proveniencia(valor):
    encontrados = []
    def visitar(item):
        if isinstance(item, str) and item.split("-", 1)[0] in {"ALG", "DOC", "OBS", "MED", "FOT", "NOR", "RES", "CON"}: encontrados.append(item)
        elif isinstance(item, dict):
            for chave, dado in item.items():
                if chave in {"proveniencia", "evidencias", "fontes", "documentos", "documentos_fonte", "ids"}: visitar(dado)
        elif isinstance(item, list):
            for dado in item: visitar(dado)
    visitar(valor)
    return list(dict.fromkeys(encontrados))


def _acrescentar_claims_globais(redacao, plano, delimitacao, final, quesitos, orcamento):
    claims = redacao["claims"]
    contador = len(claims) + 1
    catalogo_pat = {p["id"]: list(dict.fromkeys(p.get("evidencias", []) + p.get("constatacoes", []) + p.get("medicoes", []))) for p in final.get("patologias", [])}
    def add(secao, texto, tipo, fontes, *, qts=(), ques=(), pats=(), material="LOAD_BEARING"):
        nonlocal contador
        if not texto: return
        def por(prefixo):
            return [i for i in fontes if i.startswith(prefixo)]
        claims.append({"id": f"CLAIM-RED-{contador:03d}", "secao": secao, "tipo": tipo, "texto_semantico": str(texto),
            "pat_ids": list(pats), "qt_ids": list(qts), "que_ids": list(ques), "alg_ids": por("ALG-"), "doc_ids": por("DOC-"),
            "obs_ids": por("OBS-"), "med_ids": por("MED-"), "fot_ids": por("FOT-"), "nor_ids": por("NOR-"), "res_ids": por("RES-"), "con_ids": por("CON-"),
            "confianca": "ALTA", "natureza": "INTERPRETIVE", "materialidade": material})
        contador += 1
    for secao, chave, fonte_chave, tipo in (("1.4", "sintese_processual", "sintese_processual", "CONTEUDO_PROCESSUAL"), ("1.4", "tema_controvertido", "tema_controvertido", "CONTEUDO_PROCESSUAL"), ("1.5", "objeto", "objeto_material", "CONTEUDO_PROCESSUAL"), ("1.6", "objetivo", "objetivo_pericial", "CONTEUDO_PROCESSUAL")):
        fonte=delimitacao.get(fonte_chave)
        if fonte_chave=="sintese_processual" and not fonte:fonte=delimitacao.get("controversia_processual")
        add(secao, plano.get(chave), tipo, _proveniencia(fonte))
    for secao, chave, tipo in (("2.1", "metodologia", "INFERENCIA_TECNICA"), ("3.1", "dados_diligencia", "MANIFESTACAO_TECNICA"), ("3.2", "condicoes_gerais", "MANIFESTACAO_TECNICA")):
        valor = final.get(chave) or (final.get("vistoria") if chave == "dados_diligencia" else None)
        if valor:
            add(secao, _texto(valor) or str(valor), tipo, _proveniencia(valor))
    todas = list(dict.fromkeys(e for valores in catalogo_pat.values() for e in valores))
    qts = [q.get("id") for q in final.get("questoes_saneadas", []) if q.get("id")]
    resposta_tema = " ".join(q.get("conclusao", "").strip() for q in final.get("questoes_saneadas", []) if q.get("conclusao"))
    add("4.3", resposta_tema, "CONCLUSAO_DE_QT", todas, qts=qts, pats=list(catalogo_pat))
    for grupo in quesitos:
        for q in grupo["itens"]:
            fontes = list(dict.fromkeys(e for pat_id in q.get("pat_ids", []) for e in catalogo_pat.get(pat_id, [])))
            add("5", q["resposta"], "CONCLUSAO_DE_QT", fontes, qts=q.get("qt_ids", []), ques=[q["id"]] if q.get("id") else [], pats=q.get("pat_ids", []))
    for item in orcamento["itens"]:
        add("6", item.get("descricao") or item.get("servico"), "REPARABILIDADE", catalogo_pat.get(item.get("pat_id"), []), pats=[item.get("pat_id")])


def _grupos_quesitos(delimitacao, final):
    qts_finais = {q.get("id"): q for q in final.get("questoes_saneadas", [])}
    grupos = {}
    for q in delimitacao.get("quesitos", []):
        origem = q.get("origem") or q.get("parte") or "OUTROS"
        qt_ids = q.get("questoes_tecnicas_relacionadas", [])
        partes=[]
        for qid in qt_ids:
            conclusao=qts_finais.get(qid,{}).get("conclusao")
            partes.append(f"{qid}: {conclusao.strip()}" if isinstance(conclusao,str) and conclusao.strip() else f"{qid}: [INFORMAÇÃO NECESSÁRIA: dimensão técnica não saneada]")
        resposta = q.get("resposta") or " ".join(partes)
        juridico = q.get("materia_juridica_associada")
        if q.get("pertinencia") == "MATERIA_JURIDICA":
            resposta = "Matéria jurídica reservada à apreciação do Juízo."
        elif q.get("pertinencia") == "PERTINENTE_PARCIAL" and juridico:
            resposta = (resposta.strip() + " " if resposta else "") + f"Quanto à parcela jurídica ({juridico}), a apreciação compete ao Juízo."
        resposta = "R: " + resposta.strip() if isinstance(resposta, str) and resposta.strip() else "R: [INFORMAÇÃO NECESSÁRIA: resposta técnica não disponível no estado saneado]"
        grupos.setdefault(origem, []).append({
            "id": q.get("id"), "numero_original": q.get("numero_original"),
            "texto_integral": q.get("texto_integral") or q.get("texto"), "resposta": resposta,
            "qt_ids": qt_ids, "pat_ids": sorted({pid for qid in qt_ids for pid in qts_finais.get(qid,{}).get("patologias",[])}),
            "referencias_secoes": q.get("secoes_laudisticas_previstas", []), "pertinencia": q.get("pertinencia"),
        })
    ordem = {"JUIZO": 0, "JUÍZO": 0, "PARTE_AUTORA": 1, "AUTORA": 1, "PARTE_RE": 2, "PARTE_RÉ": 2, "RE": 2, "RÉ": 2}
    return [{"origem": origem, "itens": itens} for origem, itens in sorted(grupos.items(), key=lambda x: (ordem.get(x[0].upper(), 9), x[0])) if itens]


def _orcamento(final):
    itens = []
    for pat in final.get("patologias", []):
        bruto = pat.get("orcamento") or pat.get("item_orcamento")
        if pat.get("elegibilidade_orcamento")=="ELEGIVEL_ORCAMENTO_VICIO" and isinstance(bruto,dict) and bruto.get("incluir") is True:
            dados = dict(bruto) if isinstance(bruto, dict) else {"descricao": str(bruto)}
            dados["pat_id"] = pat["id"]
            itens.append(dados)
    return {"aplicavel": bool(itens), "itens": itens,
            "observacao": None if itens else "Seção sem itens: nenhum item elegível e integralmente estruturado foi fornecido pelo Motor."}


def _projetar_patologia(p):
    recomendacao=p.get("recomendacao") or {"necessaria":False,"descricao":None,"extensao":None}
    return {"id_patologia":p["id"],"local":p.get("localizacao_detalhada") or p.get("ambiente"),"sistema":p.get("sistema"),
        "alegacao_original":p.get("alegacao_original"),"alegacao_normalizada":p.get("alegacao_normalizada"),"fotografias":p.get("constatacao",{}).get("fotografias",[]),
        "manifestacao":p.get("manifestacao"),"constatacao":p.get("constatacao"),"situacao":p.get("constatacao",{}).get("situacao"),"origem":p.get("origem"),
        "criticidade":p.get("criticidade"),"vicio_construtivo":p.get("vicio_construtivo"),"tipo_vicio":p.get("vicio_construtivo",{}).get("tipo"),
        "recomendacoes_tecnicas":[recomendacao] if recomendacao.get("necessaria") else [],"reparo":recomendacao,
        "elegivel_orcamento":p.get("elegibilidade_orcamento")=="ELEGIVEL_ORCAMENTO_VICIO","conclusao_tecnica":p.get("conclusao_tecnica")}

def _montar_laudo(processo, delimitacao, final, plano, redacao, gate, grounding, fidelidade, estilo, correcoes):
    pats = final.get("patologias", [])
    normas = sorted({n for c in redacao.get("claims", []) for n in c.get("nor_ids", [])})
    qts = final.get("questoes_saneadas", [])
    sintese_tema = " ".join(q.get("conclusao", "").strip() for q in qts if q.get("conclusao"))
    ressalvas = list(dict.fromkeys(r for p in pats for r in p.get("ressalvas", []) + p.get("analise_causal", {}).get("limitacoes", [])))
    quadro = [{
        "pat_id": p["id"], "local": p.get("localizacao_detalhada") or p.get("ambiente"), "sistema": p.get("sistema"),
        "manifestacao": p.get("manifestacao"), "situacao": p["constatacao"]["situacao"],
        "origem": p.get("origem"), "criticidade": p.get("criticidade"),
        "vicio_construtivo": p.get("vicio_construtivo"), "reparo_orcamento": p.get("elegibilidade_orcamento")=="ELEGIVEL_ORCAMENTO_VICIO",
    } for p in pats]
    return {
        "schema_version": "1.1.0", "tipo_pericia": plano["tipo_pericia"], "modelo_documental": plano["modelo_documental"],
        "identificacao": {"numero_processo": processo.get("numero_processo"), "partes": processo.get("partes", [])},
        "qualificacao_perito": processo.get("qualificacao_perito"), "preambulo": processo.get("preambulo"),
        "sintese_processual": plano.get("sintese_processual"), "tema_controvertido": plano.get("tema_controvertido"),
        "objeto": plano.get("objeto"), "objetivo": plano.get("objetivo"),
        "metodologia": final.get("metodologia", []), "normas_aplicaveis": normas,
        "definicoes_necessarias": final.get("definicoes_necessarias", []), "criterios_origem": final.get("criterios_origem"),
        "criterios_criticidade": final.get("criterios_criticidade"), "limitacoes": ressalvas,
        "dados_diligencia": final.get("dados_diligencia") or final.get("vistoria"),
        "condicoes_gerais": final.get("condicoes_gerais"), "sistemas_analisados": final.get("sistemas_analisados", []),
        "analises_tecnicas": redacao["blocos"], "patologias": [_projetar_patologia(p) for p in pats],
        "conclusao_classificacoes": [{"pat_id": p["id"], "situacao": p["constatacao"]["situacao"], "origem": p["origem"], "criticidade": p["criticidade"]} for p in pats],
        "quadro_resumo": quadro, "sintese_conclusiva_tema": sintese_tema,
        "quesitos": _grupos_quesitos(delimitacao, final), "orcamento": _orcamento(final), "referencias": normas,
        "encerramento": {"nome_perito": processo.get("nome_perito"), "qualificacao": processo.get("qualificacao_perito"), "crea": processo.get("crea"), "cidade": processo.get("cidade"), "data": processo.get("data_laudo"), "quantidade_paginas": None},
        "claims_redacao": redacao["claims"],
        "metadados_de_auditoria": {"gate": gate, "grounding": grounding, "achados_fidelidade": fidelidade, "achados_estilo": estilo, "autocorrecoes": correcoes},
        "aprendizado_futuro": {"status": "NAO_IMPLEMENTADO", "redacao_agente": None, "correcao_perito": None, "redacao_final": None, "diff_semantico": None, "regra_candidata": None},
    }


def _render_markdown(laudo):
    """Representação de teste; não contém decisões de layout Word."""
    def dado(valor, nome):
        return str(valor) if valor not in (None, "", []) else f"[INFORMAÇÃO NECESSÁRIA: {nome}]"
    linhas = [
        "# 1 CONSIDERAÇÕES GERAIS", "## 1.1 Identificação do Processo", dado(laudo["identificacao"].get("numero_processo"), "número do processo"),
        "## 1.2 Qualificação do Perito Nomeado", dado(laudo["qualificacao_perito"], "qualificação do perito"),
        "## 1.3 Preâmbulo", dado(laudo["preambulo"], "preâmbulo"),
        "## 1.4 Síntese Processual e Delimitação do Tema Controvertido", dado(laudo["sintese_processual"], "síntese processual"), dado(laudo["tema_controvertido"], "tema controvertido"),
        "## 1.5 Objeto da Perícia", dado(laudo["objeto"], "objeto"), "## 1.6 Objetivo da Perícia", dado(laudo["objetivo"], "objetivo"),
        "# 2 METODOLOGIA E NORMAS TÉCNICAS", "## 2.1 Metodologia Adotada", dado(laudo["metodologia"], "metodologia"),
        "## 2.2 Normas Técnicas Aplicáveis", dado(laudo["normas_aplicaveis"], "normas aplicáveis"),
        "## 2.3 Definições Técnicas Necessárias", dado(laudo["definicoes_necessarias"], "definições necessárias"),
        "## 2.4 Classificação das Origens", dado(laudo["criterios_origem"], "critérios de origem"),
        "## 2.5 Classificação da Criticidade", dado(laudo["criterios_criticidade"], "critérios de criticidade"),
        "## 2.6 Limitações da Inspeção", dado(laudo["limitacoes"], "limitações"),
        "# 3 VISTORIA", "## 3.1 Dados da Diligência Pericial", dado(laudo["dados_diligencia"], "dados da diligência"),
        "## 3.2 Condições Gerais da Edificação", dado(laudo["condicoes_gerais"], "condições gerais"), "## 3.3 Análise dos Sistemas Construtivos",
    ]
    for bloco in laudo["analises_tecnicas"]:
        linhas.append(f"### {bloco['pat_id']}")
        for titulo, texto in zip(bloco["titulos"], bloco["textos"]): linhas.extend((f"#### {titulo}", texto))
    linhas.extend(("# 4 CONCLUSÃO", "## 4.1 Avaliação das Classificações", dado(laudo["conclusao_classificacoes"], "classificações"),
                   "## 4.2 Quadro-Resumo das Manifestações Analisadas", dado(laudo["quadro_resumo"], "quadro-resumo"),
                   "## 4.3 Síntese Conclusiva do Tema Controvertido", dado(laudo["sintese_conclusiva_tema"], "resposta ao tema"), "# 5 QUESITOS"))
    for grupo in laudo["quesitos"]:
        linhas.append(f"## {grupo['origem']}")
        for q in grupo["itens"]: linhas.extend((f"**Quesito {dado(q.get('numero_original'), 'numeração original')}:** {dado(q.get('texto_integral'), 'texto do quesito')}", q["resposta"]))
    linhas.extend(("# 6 ORÇAMENTO", dado(laudo["orcamento"]["itens"], "itens orçamentários"), "# 7 REFERÊNCIAS BIBLIOGRÁFICAS", dado(laudo["referencias"], "referências utilizadas"), "# 8 ENCERRAMENTO", dado(laudo["encerramento"], "dados de encerramento")))
    return "\n\n".join(linhas) + "\n"


def executar_pipeline_redacao(processo, delimitacao, motor):
    from scripts.motor_vicios.pipeline import recalcular_gate
    estado={"erros":motor.get("erros_finais",[]),"detector":motor.get("detector_final",[]),"deep":motor.get("deep_audit_final",[]),
            "materiais":[a for a in motor.get("grounding_final",[]) if a.get("saliencia")=="LOAD_BEARING"],
            "proposition_bloqueante":any(x.get("verdict")!="SUPPORTED" for x in motor.get("proposition_audit_results",[])),
            "autoauditoria":motor.get("analise_final",{}).get("autoauditoria",[]),
            "ressalvas":any(p.get("ressalvas") or p.get("analise_causal",{}).get("grau_certeza")=="INCONCLUSIVO" for p in motor.get("analise_final",{}).get("patologias",[]))}
    auditavel=any(k in motor for k in ("erros_finais","detector_final","deep_audit_final","grounding_final","proposition_audit_results","coverage_execucao"))
    if auditavel:
        from scripts.planejamento_pericial.validar_plano import recalcular_execucao
        entradas=motor.get("coverage_inputs") or {}
        cobertura_recalculada=recalcular_execucao(entradas.get("plano",{}),entradas.get("vistoria",{}))
        if not cobertura_recalculada["apto"]:estado["erros"]=[*estado["erros"],"coverage executada insuficiente"]
    gate_recalculado=recalcular_gate(estado) if auditavel else motor.get("gate")
    if auditavel and (motor.get("gate") not in {None,gate_recalculado} or gate_recalculado=="BLOQUEADO_PARA_REDACAO"):motor={**motor,"gate":"BLOQUEADO_PARA_REDACAO"}
    plano = planejar(processo, delimitacao, motor)
    inicial = redigir(plano, motor)
    if plano["status"] == "BLOQUEADO" or inicial["status"] == "BLOQUEADO":
        tipo = "MODELO_DOCUMENTAL_INCOMPATIVEL" if plano.get("modelo_documental") is None else "GATE_TECNICO_BLOQUEADO"
        return {"plano_redacao": plano, "redacao_inicial": inicial, "redacao_final": inicial, "gate": "BLOQUEADO_PARA_LAUDO", "achados": [{"tipo": tipo, "bloqueante": True}], "metricas": {}}
    final = motor.get("analise_final", motor)
    estilo = auditar_estilo(inicial["texto_markdown"])
    redundancia = auditar_redundancia_estrutural(plano.get("tema_controvertido"), plano.get("objeto"), plano.get("objetivo"))
    corrigida, correcoes = autocorrigir(inicial, estilo)
    quesitos = _grupos_quesitos(delimitacao, final); orcamento = _orcamento(final)
    _acrescentar_claims_globais(corrigida, plano, delimitacao, final, quesitos, orcamento)
    ids_processuais=sorted({i for chave in ("sintese_processual","controversia_processual","tema_controvertido","objeto_material","objetivo_pericial") for i in _proveniencia(delimitacao.get(chave)) if i.startswith("DOC-")})
    documentos_reais={}
    for documento in processo.get("documentos",[]):
        if documento.get("status") != "PRESENTE": continue
        aliases=[]
        if documento.get("id"):aliases.append(documento["id"])
        origem=str(documento.get("observacoes") or "").removeprefix("Origem estrutural: ").strip()
        if origem.startswith("DOC-"):aliases.append(origem)
        for alias in aliases:documentos_reais[alias]=documento
    catalogo_processual=[{"id":i,"tipo":"DOCUMENTO","classe_probatoria":"EVIDENCIA_PRIMARIA","data":documentos_reais[i].get("data"),"documento_processual":documentos_reais[i].get("id"),"proveniencia":[str(documentos_reais[i].get("observacoes") or i)],"aspectos_suportados":["FATO_PROCESSUAL"],"aspectos_contraditos":[],"acessivel":True} for i in ids_processuais if i in documentos_reais]
    grounding = auditar_grounding_redacao(corrigida, {**motor,"catalogo_processual":catalogo_processual})
    fidelidade = auditar_fidelidade(corrigida, {**final,"catalogo_evidencias":final.get("catalogo_evidencias",[])+catalogo_processual})
    provisoria = _montar_laudo(processo, delimitacao, final, plano, corrigida, "BLOQUEADO_PARA_LAUDO", grounding, fidelidade, estilo + redundancia, correcoes)
    semanticos = auditar_laudo_semantico(provisoria, final)
    qts_materiais = {q["id"] for q in final.get("questoes_saneadas", []) if q.get("status") != "PREJUDICADA"}
    qts_cobertas = {q for c in corrigida["claims"] for q in c.get("qt_ids", [])}
    ausentes = sorted(qts_materiais - qts_cobertas)
    materiais = [a for a in grounding if next((c for c in corrigida["claims"] if c["id"] == a["claim_red_id"]), {}).get("materialidade") == "LOAD_BEARING"]
    tem_ressalva = bool(provisoria["limitacoes"] or any(p.get("analise_causal", {}).get("grau_certeza") == "INCONCLUSIVO" for p in final.get("patologias", [])))
    gate = recalcular_gate_redacao(fidelidade=fidelidade,semanticos=semanticos,ausentes=ausentes,materiais=materiais,tem_ressalva=tem_ressalva)
    laudo = _montar_laudo(processo, delimitacao, final, plano, corrigida, gate, grounding, fidelidade + semanticos, estilo + redundancia, correcoes)
    metricas = {
        "claims_redigidas": len(corrigida["claims"]), "claims_grounded": sum(a.get("veredito") == "GROUNDED" for a in grounding),
        "claims_bloqueadas": sum(a.get("veredito") in REPROVADOS for a in grounding), "qt_representadas": len(qts_cobertas),
        "quesitos_respondidos": sum(len(g["itens"]) for g in laudo["quesitos"]), "ressalvas_preservadas": len(laudo["limitacoes"]),
        "contradicoes_pat_texto": sum(a.get("bloqueante", False) for a in fidelidade + semanticos), "maneirismos_detectados": len(estilo),
        "maneirismos_corrigidos": len(correcoes), "redundancias_removidas": len(redundancia),
        "terminologia_inconsistente": sum(a["tipo"] == "TERMINOLOGIA_INSTAVEL" for a in estilo), "normas_utilizadas": len(laudo["referencias"]),
        "referencias_nao_utilizadas": sum(a["tipo"] == "REFERENCIA_NAO_UTILIZADA" for a in semanticos),
        "paragrafos_sem_funcao": sum(a["tipo"] == "PARAGRAFO_SEM_FUNCAO" for a in estilo), "tema_respondido": bool(laudo["sintese_conclusiva_tema"]),
    }
    achados = fidelidade + semanticos + estilo + redundancia
    return {"plano_redacao": plano, "redacao_inicial": inicial, "redacao_final": corrigida,
            "blocos_redacao": corrigida["blocos"], "laudo": laudo, "laudo_texto_md": _render_markdown(laudo),
            "grounding": grounding, "relatorio_auditoria_redacao": {"achados": fidelidade + semanticos, "grounding": grounding},
            "relatorio_estilo": {"achados": estilo + redundancia, "autocorrecoes": correcoes},
            "gate_redacao": {"status": gate, "bloqueios": [a for a in achados if a.get("bloqueante")]},
            "achados": achados, "autocorrecoes": correcoes, "qt_ausentes": ausentes, "gate": gate, "metricas": metricas}

"""Compara texto e claims com PAT_FINAL e evidências primárias."""

from __future__ import annotations
import re
import unicodedata

from scripts.auditoria_pericial.grounding import auditar_claim
from scripts.motor_vicios.auditar import comparar_medicao

TIPO_CLAIM = {"MANIFESTACAO_TECNICA": "MANIFESTACAO_TECNICA", "INFERENCIA_TECNICA": "INFERENCIA_TECNICA", "ORIGEM": "ORIGEM", "CONCLUSAO_DE_QT": "CONCLUSAO_DE_QT", "REPARABILIDADE": "REPARABILIDADE"}


def _n(texto):
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()


def auditar_grounding_redacao(redacao, motor_final):
    final = motor_final.get("analise_final", motor_final)
    catalogo = final.get("catalogo_evidencias", [])
    por_id = {e.get("id"): e for e in catalogo}
    saida = []
    for claim in redacao.get("claims", []):
        ids = sum((claim.get(k, []) for k in ("obs_ids", "med_ids", "fot_ids", "doc_ids", "nor_ids", "res_ids", "con_ids")), [])
        rel = [por_id[i] for i in ids if i in por_id]
        tipo = TIPO_CLAIM.get(claim["tipo"], "INFERENCIA_TECNICA")
        requerido = [tipo]
        if tipo in {"MANIFESTACAO_TECNICA", "CONCLUSAO_DE_QT"}: requerido = ["CONSTATACAO_DE_VISTORIA"]
        interno = {"id": claim["id"].replace("CLAIM-RED-", "CLM-"), "tipo": tipo, "natureza": claim["natureza"], "saliencia": claim["materialidade"], "texto": claim["texto_semantico"], "aspectos_requeridos": requerido}
        try: resultado = auditar_claim(interno, rel, catalogo)
        except ValueError: resultado = {"claim_id": claim["id"], "veredito": "UNVERIFIABLE", "evidencias": []}
        resultado["claim_red_id"] = claim["id"]
        resultado["componente"] = "TECNICO"
        saida.append(resultado)
        if claim.get("nor_ids"):
            normas_rel = [por_id[i] for i in claim["nor_ids"] if i in por_id]
            normativo = {"id": claim["id"].replace("CLAIM-RED-", "CLM-"), "tipo": "REQUISITO_NORMATIVO", "natureza": "FACTUAL", "saliencia": claim["materialidade"], "texto": claim["texto_semantico"], "aspectos_requeridos": ["REQUISITO_NORMATIVO_VERIFICADO"]}
            try: audit_norma = auditar_claim(normativo, normas_rel, catalogo)
            except ValueError: audit_norma = {"claim_id": claim["id"], "veredito": "UNVERIFIABLE", "evidencias": []}
            audit_norma["claim_red_id"] = claim["id"]
            audit_norma["componente"] = "NORMATIVO"
            saida.append(audit_norma)
    return saida


def auditar_fidelidade(redacao, motor_final):
    final = motor_final.get("analise_final", motor_final); pats = {p["id"]: p for p in final.get("patologias", [])}; achados = []
    normas = {n["id"] for p in pats.values() for n in p.get("normas_relacionadas", []) if n.get("verificada")}
    catalogo = {e.get("id"): e for e in final.get("catalogo_evidencias", [])}
    def add(tipo, pat_id, esperado, atual): achados.append({"tipo": tipo, "severidade": "CRITICO", "pat_id": pat_id, "esperado": esperado, "atual": atual, "bloqueante": True})
    for bloco in redacao.get("blocos", []):
        pat = pats.get(bloco.get("pat_id")); texto = " ".join(bloco.get("textos", [])); n = _n(texto)
        if not pat: add("UNSUPPORTED_REDRAFT_CLAIM", bloco.get("pat_id"), "PAT existente", "PAT ausente"); continue
        if len(bloco.get("textos", [])) != 4 or bloco.get("titulos") != ["Análise das Alegações e Prováveis Causas", "Consequências", "Classificação", "Conclusão"]: add("SECAO_MATERIAL_AUSENTE", pat["id"], "quatro blocos canônicos", bloco.get("titulos"))
        elif bloco["textos"][3] != pat.get("conclusao_tecnica"): add("CONCLUSAO_ALTERADA", pat["id"], pat.get("conclusao_tecnica"), bloco["textos"][3])
        classificacao = _n(bloco.get("textos", ["", "", ""])[2]) if len(bloco.get("textos", [])) >= 3 else ""
        esperados = {
            "situacao": _n(str(pat["constatacao"]["situacao"]).replace("_", " ")),
            "origem": _n(str(pat.get("origem", "")).replace("ENDOGENA_CONSTRUTIVA", "ENDOGENA/CONSTRUTIVA").replace("_", " ")),
            "criticidade": _n(str(pat.get("criticidade", "")).replace("_", " ")),
        }
        if any(valor and valor not in classificacao for valor in esperados.values()):
            add("CLASSIFICACAO_ALTERADA", pat["id"], esperados, bloco.get("textos", [None, None, None])[2])
        if pat["constatacao"]["situacao"] == "NAO_CONSTATADA" and re.search(r"\b(nao existe|inexistente)\b", n): add("NAO_CONSTATADA_CONVERTIDA_EM_INEXISTENTE", pat["id"], "não constatada", texto)
        if pat.get("origem") == "INCONCLUSIVA" and "endogena/construtiva" in n: add("ORIGEM_ALTERADA", pat["id"], "INCONCLUSIVA", "ENDOGENA_CONSTRUTIVA")
        if pat.get("criticidade") == "MEDIA" and any(x in n for x in ("criticidade critica", "gravissima", "inequivoc")): add("CRITICIDADE_INFLADA", pat["id"], "MEDIA", texto)
        grau = pat.get("analise_causal", {}).get("grau_certeza")
        if grau in {"INCONCLUSIVO", "POSSIVEL"} and re.search(r"\b(decorre|e causada|comprovadamente|inequivocamente)\b", n): add("CAUSA_INCONCLUSIVA_FECHADA", pat["id"], grau, texto)
        if "foi constatado que o morador" in n or "constatou-se que o morador" in n: add("DECLARACAO_CONVERTIDA_EM_CONSTATACAO", pat["id"], "declaração", texto)
        for ressalva in pat.get("ressalvas", []) + pat.get("analise_causal", {}).get("limitacoes", []):
            if _n(ressalva) not in n: add("RESSALVA_ENFRAQUECIDA", pat["id"], ressalva, "ausente")
    conhecidos = {c["id"] for c in redacao.get("claims", [])}
    claims_por_id = {c["id"]: c for c in redacao.get("claims", [])}
    for bloco in redacao.get("blocos", []):
        if any(i not in conhecidos for i in bloco.get("claim_ids", [])): add("UNSUPPORTED_REDRAFT_CLAIM", bloco.get("pat_id"), "claim registrada", "claim nova")
        for cid, texto in zip(bloco.get("claim_ids", []), bloco.get("textos", [])):
            if cid in claims_por_id and claims_por_id[cid].get("texto_semantico") != texto: add("CLAIM_TEXTO_DIVERGENTE", bloco.get("pat_id"), texto, claims_por_id[cid].get("texto_semantico"))
    for claim in redacao.get("claims", []):
        pat_id = claim.get("pat_ids", [None])[0] if claim.get("pat_ids") else None
        if pat_id is not None and pat_id not in pats: add("UNSUPPORTED_REDRAFT_CLAIM", pat_id, "PAT final", claim.get("texto_semantico"))
        for norma in claim.get("nor_ids", []):
            if norma not in normas: add("NORMA_INVENTADA", pat_id, sorted(normas), norma)
        texto = claim.get("texto_semantico", "")
        if re.search(r"\bitem\s+\d+(?:\.\d+)+\b", _n(texto)) and not claim.get("nor_ids"): add("NORMA_INVENTADA", pat_id, "item normativo verificado", texto)
        for med_id in claim.get("med_ids", []):
            med = catalogo.get(med_id, {}); valor = med.get("valor"); unidade = med.get("unidade")
            numeros = re.findall(r"\b\d+(?:[,.]\d+)?\s*(?:mm|cm|m|%)\b", _n(texto))
            if valor is not None and not comparar_medicao(texto, med, permitir_conversao=False): add("MEDICAO_ALTERADA", pat_id, f"{valor} {unidade}", numeros or "valor/unidade ausente")
    return achados


def auditar_laudo_semantico(laudo, motor_final):
    """Confere projeções repetidas do PAT sem alterar o artefato auditado."""
    final = motor_final.get("analise_final", motor_final)
    pats = {p["id"]: p for p in final.get("patologias", [])}
    achados = []
    def add(tipo, identificador, esperado, atual):
        achados.append({"tipo": tipo, "severidade": "CRITICO", "pat_id": identificador,
                        "esperado": esperado, "atual": atual, "bloqueante": True})
    for linha in laudo.get("quadro_resumo", []):
        pat = pats.get(linha.get("pat_id"))
        if not pat:
            add("QUADRO_PAT_INEXISTENTE", linha.get("pat_id"), "PAT_FINAL", linha); continue
        esperado = (pat["constatacao"]["situacao"], pat["origem"], pat["criticidade"])
        atual = (linha.get("situacao"), linha.get("origem"), linha.get("criticidade"))
        if atual != esperado: add("QUADRO_RESUMO_DIVERGENTE", pat["id"], esperado, atual)
    for item in laudo.get("orcamento", {}).get("itens", []):
        pat = pats.get(item.get("pat_id"))
        elegivel = bool(pat and pat.get("elegivel_orcamento") is True and
                        pat.get("constatacao", {}).get("situacao") == "ANOMALIA" and
                        pat.get("origem") == "ENDOGENA_CONSTRUTIVA")
        if not elegivel: add("ORCAMENTO_INELEGIVEL", item.get("pat_id"), "PAT elegível pelo Motor", item)
        if "manuten" in _n(item.get("descricao", "") + " " + item.get("servico", "")):
            add("ORCAMENTO_MANUTENCAO_INDEVIDA", item.get("pat_id"), "reparo elegível", item)
        faltantes = [k for k in ("servico", "quantitativo", "memoria_calculo") if not item.get(k)]
        if faltantes: add("ORCAMENTO_SEM_REQUISITOS", item.get("pat_id"), faltantes, item)
    usados = {n for c in laudo.get("claims_redacao", []) for n in c.get("nor_ids", [])}
    extras = set(laudo.get("referencias", [])) - usados
    if extras: add("REFERENCIA_NAO_UTILIZADA", None, sorted(usados), sorted(extras))
    tema = _n(laudo.get("tema_controvertido", "")); resposta = _n(laudo.get("sintese_conclusiva_tema", ""))
    fundamentos_tema = [_n(q.get("conclusao")) for q in final.get("questoes_saneadas", []) if q.get("conclusao")]
    if tema and (not resposta or not fundamentos_tema or not all(f in resposta for f in fundamentos_tema)):
        add("TEMA_NAO_RESPONDIDO", None, fundamentos_tema, resposta)
    for campo in ("sintese_processual", "tema_controvertido", "objeto", "objetivo"):
        if not laudo.get(campo): add("SECAO_MATERIAL_AUSENTE", campo, "conteúdo rastreável", laudo.get(campo))
    for grupo in laudo.get("quesitos", []):
        for q in grupo.get("itens", []):
            resposta_q = str(q.get("resposta", "")).strip()
            if (not resposta_q or "[informacao necessaria:" in _n(resposta_q) or
                    _n(resposta_q).strip(". ") in {"r: vide laudo", "vide laudo"}):
                add("QUESITO_SEM_RESPOSTA_TECNICA", q.get("id"), "R: resposta objetiva", resposta_q)
            for campo in ("id", "numero_original", "texto_integral"):
                if not q.get(campo): add("QUESITO_INCOMPLETO", q.get("id"), campo, q.get(campo))
            if not q.get("referencias_secoes"): add("QUESITO_SEM_REFERENCIA_TECNICA", q.get("id"), "seção técnica", [])
            fundamentos = [x.get("conclusao") for x in final.get("questoes_saneadas", []) if x.get("id") in q.get("qt_ids", []) and x.get("conclusao")]
            if fundamentos and not any(_n(f) in _n(resposta_q) for f in fundamentos):
                add("QUESITO_CRIA_CONCLUSAO_NOVA", q.get("id"), fundamentos, resposta_q)
    for pat in pats.values():
        if pat.get("elegivel_orcamento") is True and not any(i.get("pat_id") == pat["id"] for i in laudo.get("orcamento", {}).get("itens", [])):
            add("ORCAMENTO_ELEGIVEL_INCOMPLETO", pat["id"], "item completo", "ausente")
    return achados

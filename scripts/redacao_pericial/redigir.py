"""Expressa o PAT_FINAL em blocos canônicos, sem recalcular o diagnóstico."""

from __future__ import annotations
from scripts.motor_vicios.auditar import comparar_medicao


TITULOS = (
    "Análise das Alegações e Prováveis Causas",
    "Consequências",
    "Classificação",
    "Conclusão",
)
ROTULOS = {
    "ENDOGENA_CONSTRUTIVA": "ENDÓGENA/CONSTRUTIVA",
    "USO_OPERACAO_MANUTENCAO": "USO/OPERAÇÃO/MANUTENÇÃO",
    "NAO_APLICAVEL": "NÃO APLICÁVEL",
    "NAO_CONSTATADA": "NÃO CONSTATADA",
    "CRITICA": "CRÍTICA", "MEDIA": "MÉDIA", "MINIMA": "MÍNIMA",
}


def _rotulo(valor):
    return ROTULOS.get(valor, str(valor).replace("_", " "))


def _claim(indice, tipo, texto, pat, fontes, medicoes=(), materialidade="LOAD_BEARING", natureza="INTERPRETIVE", qt_ids=(), que_ids=()):
    por_prefixo = lambda prefixo: [x for x in fontes if x.startswith(prefixo)]
    normas_citadas = [x for x in por_prefixo("NOR-") if x in texto]
    return {
        "id": f"CLAIM-RED-{indice:03d}", "secao": f"PAT:{pat['id']}", "tipo": tipo, "texto_semantico": texto,
        "pat_ids": [pat["id"]], "qt_ids": list(qt_ids), "que_ids": list(que_ids),
        "alg_ids": list(pat.get("alegacoes_relacionadas", [])), "obs_ids": por_prefixo("OBS-"),
        "med_ids": [m["id"] for m in medicoes if m.get("id") in por_prefixo("MED-") and comparar_medicao(texto,m,permitir_conversao=False)], "fot_ids": por_prefixo("FOT-"), "doc_ids": por_prefixo("DOC-"),
        "nor_ids": normas_citadas, "res_ids": por_prefixo("RES-"), "con_ids": por_prefixo("CON-"),
        "confianca": pat.get("confianca", {}).get("nivel", pat.get("confianca", "MEDIA")),
        "natureza": natureza, "materialidade": materialidade,
    }


def _analise(pat):
    partes = []
    if pat.get("alegacoes_relacionadas"):
        partes.append("A manifestação foi analisada a partir das alegações identificadas nos autos.")
    situacao = pat["constatacao"]["situacao"]
    descricao = pat["constatacao"].get("descricao")
    if situacao == "NAO_CONSTATADA":
        partes.append(f"Na data da vistoria, {descricao.rstrip('.').lower()} não foi constatada.")
        partes.append("Essa constatação não permite afirmar que o fenômeno jamais tenha ocorrido.")
    elif descricao:
        partes.append(f"Na vistoria, constatou-se: {descricao.rstrip('.')}.")
    causa = pat.get("causa") or pat.get("analise_causal", {}).get("causa_provavel")
    grau = pat.get("analise_causal", {}).get("grau_certeza")
    if causa and grau not in {"INCONCLUSIVO", "POSSIVEL"}:
        prefixo = "Os elementos disponíveis sustentam" if grau == "CONFIRMADO" else "Os elementos são compatíveis com"
        partes.append(f"{prefixo} {causa.rstrip('.').lower()}.")
    else:
        partes.append("Os elementos disponíveis não permitem individualizar a causa específica.")
    for ressalva in pat.get("ressalvas", []) + pat.get("analise_causal", {}).get("limitacoes", []):
        if ressalva:
            partes.append(ressalva.rstrip(".") + ".")
    return " ".join(partes)


def _consequencias(pat):
    trechos = []
    for dimensao, dado in pat.get("consequencias", {}).items():
        if dado.get("status") in {"PRESENTE", "AUSENTE", "INCONCLUSIVA"} and dado.get("fundamentacao"):
            trechos.append(f"{dimensao.capitalize()}: {dado['fundamentacao'].rstrip('.')}.")
    return " ".join(trechos) or "Não foram registradas consequências técnicas adicionais no PAT final."


def _classificacao(pat):
    texto = (f"Situação: {_rotulo(pat['constatacao']['situacao'])}. "
             f"Origem: {_rotulo(pat['origem'])}. Criticidade: {_rotulo(pat['criticidade'])}.")
    vicio = pat.get("vicio_construtivo")
    if isinstance(vicio, dict) and "caracterizado" in vicio:
        texto += " Vício construtivo: " + ("CARACTERIZADO." if vicio["caracterizado"] else "NÃO CARACTERIZADO.")
    return texto


def redigir(plano, motor_final):
    if plano.get("gate_tecnico") == "BLOQUEADO_PARA_REDACAO":
        return {"schema_version": "1.0.0", "status": "BLOQUEADO", "blocos": [], "claims": [], "texto_markdown": ""}
    final = motor_final.get("analise_final", motor_final)
    medicoes=[e for e in final.get("catalogo_evidencias",[]) if e.get("id","").startswith("MED-")]
    blocos, claims, contador = [], [], 1
    for pat in final.get("patologias", []):
        secao = next((s for s in plano.get("unidades_patologia", []) if pat["id"] == s["pat_id"]), {})
        fontes = secao.get("evidencias_permitidas", [])
        textos = [
            _analise(pat),
            _consequencias(pat),
            _classificacao(pat),
            pat["conclusao_tecnica"],
        ]
        tipos = ["MANIFESTACAO_TECNICA", "INFERENCIA_TECNICA", "ORIGEM", "CONCLUSAO_DE_QT"]
        ids = []
        for tipo, texto in zip(tipos, textos):
            claim = _claim(contador, tipo, texto, pat, fontes, medicoes, qt_ids=secao.get("qt_ids", []), que_ids=secao.get("que_ids", []))
            claims.append(claim); ids.append(claim["id"]); contador += 1
        blocos.append({"pat_id": pat["id"], "titulos": list(TITULOS), "textos": textos, "claim_ids": ids})
    markdown = "\n\n".join(
        f"## {b['pat_id']}\n\n" + "\n\n".join(f"### {t}\n\n{x}" for t, x in zip(b["titulos"], b["textos"]))
        for b in blocos
    )
    return {"schema_version": "1.1.0", "status": "REDIGIDO", "blocos": blocos, "claims": claims, "texto_markdown": markdown}

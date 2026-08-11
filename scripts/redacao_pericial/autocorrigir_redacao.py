"""Correções editoriais conservadoras; nunca altera dado técnico."""

from __future__ import annotations
from copy import deepcopy
import re

REMOVIVEIS = ("É importante destacar que ", "Cumpre ressaltar que ", "Vale salientar que ", "Importa mencionar que ")
TITULOS_IMUTAVEIS={"classificação","conclusão"}
CLAIMS_IMUTAVEIS={"ORIGEM","CONCLUSAO_DE_QT","CLASSIFICACAO","CONCLUSAO"}


def autocorrigir(redacao, achados):
    corrigida = deepcopy(redacao); correcoes = []
    claims = {c["id"]: c for c in corrigida.get("claims", [])}
    editoriais = {a["tipo"] for a in achados if a.get("severidade") == "EDITORIAL"}
    for bloco in corrigida.get("blocos", []):
        novos = []
        for indice, texto in enumerate(bloco.get("textos", [])):
            original = texto
            titulo=(bloco.get("titulos",[])[indice] if indice<len(bloco.get("titulos",[])) else "").casefold()
            claim=claims.get(bloco.get("claim_ids",[])[indice]) if indice<len(bloco.get("claim_ids",[])) else None
            if bloco.get("material") is True or titulo in TITULOS_IMUTAVEIS or (claim and (claim.get("imutavel") is True or claim.get("material") is True or claim.get("tipo") in CLAIMS_IMUTAVEIS)):
                novos.append(texto);continue
            if "ABERTURA_GENERICA" in editoriais:
                for termo in REMOVIVEIS: texto = texto.replace(termo, "")
            if "CONECTIVO_REPETITIVO" in editoriais:
                texto = re.sub(r"(?i)\b(ademais|destarte|assim sendo|em síntese),?\s*", "", texto)
            if "TERMINOLOGIA_INSTAVEL" in editoriais:
                texto = re.sub(r"(?i)\b(manifestação fissurativa|abertura patológica|descontinuidade superficial)\b", "fissura", texto)
            if "TOM_PROFESSORAL" in editoriais:
                texto = re.sub(r"(?i)\b(para que o leitor compreenda|cumpre explicar inicialmente|antes de prosseguir, deve-se compreender),?\s*", "", texto)
            if "CONCLUSAO_REPETIDA" in editoriais and "\n\n" in texto:
                partes = [p.strip() for p in texto.split("\n\n") if p.strip()]
                texto = "\n\n".join(dict.fromkeys(partes))
            if texto != original: correcoes.append({"tipo": "AJUSTE_EDITORIAL", "antes": original, "depois": texto})
            if texto != original and indice < len(bloco.get("claim_ids", [])):
                claim = claims.get(bloco["claim_ids"][indice])
                if claim and claim.get("texto_semantico") == original:
                    claim["texto_semantico"] = texto
            novos.append(texto)
        bloco["textos"] = novos
    corrigida["texto_markdown"] = "\n\n".join(
        f"## {b['pat_id']}\n\n" + "\n\n".join(f"### {t}\n\n{x}" for t, x in zip(b["titulos"], b["textos"])) for b in corrigida.get("blocos", [])
    )
    return corrigida, correcoes

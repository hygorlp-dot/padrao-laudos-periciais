"""Normalização auditável de identificadores numéricos do PJe."""

import re


def normalizar_id_pje(valor: str) -> dict:
    original = str(valor or "")
    normalizado = re.sub(r"\s+", "", original)
    if "\n" in original or "\r" in original:
        metodo = "REMOCAO_QUEBRAS_LINHA"
    elif normalizado != original:
        metodo = "REMOCAO_ESPACOS"
    else:
        metodo = "SEM_ALTERACAO"
    if not normalizado.isdigit():
        raise ValueError(f"ID PJe não numérico: {original!r}")
    return {
        "valor_original": original,
        "valor_normalizado": normalizado,
        "metodo": metodo,
        "confianca": {"nivel": "ALTA", "score": 1.0},
    }

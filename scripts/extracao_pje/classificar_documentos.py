"""Classificador documental determinístico, conservador e explicável."""

import re
import unicodedata

from .regras_classificacao import REGRAS_CONTEM, REGRAS_EXATAS


def normalizar_busca(texto):
    base = unicodedata.normalize("NFKD", texto or "")
    return re.sub(r"\s+", " ", "".join(c for c in base if not unicodedata.combining(c)).lower()).strip()


def classificar_documento(titulo, tipo, primeira_pagina="", secoes=None):
    titulo_n, tipo_n = normalizar_busca(titulo), normalizar_busca(tipo)
    pagina_n = normalizar_busca(primeira_pagina)
    secoes = secoes or []
    for termo, classe in REGRAS_EXATAS:
        if titulo_n == termo or tipo_n == termo:
            return _resultado(classe, "ALTA", 1.0, [f"correspondência exata: {termo}"], False, secoes)
    # A palavra laudo isolada nunca autoriza classificação técnica/judicial.
    if titulo_n in {"laudo", "laudo pericial", "laudo tecnico"} or tipo_n in {"laudo", "laudo pericial", "laudo tecnico"}:
        return _resultado("OUTRO", "BAIXA", 0.3, ["título LAUDO sem evidência adicional suficiente"], True, secoes)
    parecer = "parecer tecnico" in f"{titulo_n} {tipo_n} {pagina_n}"
    registro = bool(re.search(r"\b(crea|cau)\b", pagina_n))
    apoio = any(s["tipo_normalizado"] in {"RELATORIO_FOTOGRAFICO", "ORCAMENTO"} for s in secoes)
    if parecer and registro:
        criterios = ["expressão parecer técnico", "registro CREA/CAU na primeira página"]
        if apoio:
            criterios.append("seção estrutural de apoio detectada")
        return _resultado("PARECER_TECNICO_PARTE", "MEDIA", 0.8, criterios, True, secoes)
    for termo, classe in REGRAS_CONTEM:
        if termo in titulo_n or termo in tipo_n:
            return _resultado(classe, "ALTA", 0.9, [f"termo inequívoco em título/tipo: {termo}"], False, secoes)
    return _resultado("OUTRO", "BAIXA", 0.3, ["nenhuma regra determinística segura aplicável"], True, secoes)


def _resultado(classe, nivel, score, criterios, pendente, secoes):
    tipos = {s["tipo_normalizado"] for s in secoes}
    composto = len(tipos & {"RELATORIO_FOTOGRAFICO", "ORCAMENTO", "MEMORIA_CALCULO", "ANEXO"}) >= 2
    return {"classe_normalizada": classe, "subclasse_normalizada": "DOCUMENTO_COMPOSTO" if composto else None,
            "confianca_classificacao": {"nivel": nivel, "score": score}, "criterios_classificacao": criterios,
            "status_revisao": "PENDENTE_REVISAO" if pendente or nivel == "BAIXA" else "REVISADO_AUTOMATICAMENTE"}

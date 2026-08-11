"""Auditoria contextual de linguagem pericial natural."""

from __future__ import annotations
import re
import unicodedata

ABERTURAS = ("e importante destacar que", "cumpre ressaltar que", "vale salientar que", "importa mencionar que")
CONECTIVOS = ("nesse contexto", "nesse sentido", "diante desse cenario", "ademais", "por conseguinte", "destarte", "dessa forma", "assim sendo", "em sintese")
METADISCURSO = ("a analise a seguir tem por objetivo", "este topico busca demonstrar", "conforme sera apresentado")
VAZIOS = ("robusta", "robusto", "abrangente", "minuciosa", "minucioso", "crucial", "notavel")
HIPERBOLES = ("inequivoca", "inequivoco", "cabalmente", "incontestavel", "comprovadamente")
PROFESSORAL = ("para que o leitor compreenda", "cumpre explicar inicialmente", "antes de prosseguir, deve-se compreender")
FUNCOES = ("alega", "informa", "declar", "constat", "observ", "med", "indica", "sustenta", "permite", "limita", "classific", "conclu", "não ", "nao ")


def _normalizar(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def auditar_estilo(texto, confianca=None):
    n = _normalizar(texto); achados = []
    def add(tipo, severidade, trecho): achados.append({"tipo": tipo, "severidade": severidade, "trecho": trecho})
    aberturas = sum(n.count(x) for x in ABERTURAS)
    conectivos = sum(n.count(x) for x in CONECTIVOS)
    vazios = [x for x in VAZIOS if re.search(rf"\b{re.escape(x)}\b", n)]
    if aberturas >= 2: add("ABERTURA_GENERICA", "EDITORIAL", str(aberturas))
    if conectivos >= 3: add("CONECTIVO_REPETITIVO", "EDITORIAL", str(conectivos))
    if len(vazios) >= 2: add("ADJETIVACAO_VAZIA", "EDITORIAL", ", ".join(vazios))
    if any(x in n for x in METADISCURSO): add("METADISCURSO", "EDITORIAL", "abertura metadiscursiva")
    if any(x in n for x in HIPERBOLES) and confianca not in {"ALTA", "CONFIRMADO"}: add("HIPERBOLE_DE_CERTEZA", "IMPORTANTE", str(confianca))
    paragrafos = [re.sub(r"\s+", " ", p).strip().lower() for p in re.split(r"\n\s*\n", texto) if p.strip() and not p.lstrip().startswith("#")]
    if any(a == b for a, b in zip(paragrafos, paragrafos[1:])): add("CONCLUSAO_REPETIDA", "EDITORIAL", "parágrafo adjacente duplicado")
    if n.count("foi constatad") >= 3: add("PARALELISMO_MECANICO", "EDITORIAL", "foi constatado")
    sinonimos = sum(x in n for x in ("fissura", "manifestacao fissurativa", "abertura patologica", "descontinuidade superficial"))
    if sinonimos >= 3: add("TERMINOLOGIA_INSTAVEL", "EDITORIAL", "fissura")
    if "abordagem robusta" in n or "rigorosa investigacao" in n: add("TOM_PROMOCIONAL", "EDITORIAL", "autopromoção")
    if any(x in n for x in PROFESSORAL): add("TOM_PROFESSORAL", "EDITORIAL", "explicação elementar")
    listas = re.findall(r"(?:^|\n)\s*[-*]\s+[^\n]+(?:\n\s*[-*]\s+[^\n]+){2,}", texto)
    if listas and not any(x in n for x in ("quesito", "referencia", "quadro-resumo")):
        add("LISTA_ARTIFICIAL", "EDITORIAL", "enumeração sem função demonstrada")
    for p in paragrafos:
        if len(p.split()) >= 12 and not any(f in _normalizar(p) for f in FUNCOES):
            add("PARAGRAFO_SEM_FUNCAO", "EDITORIAL", p[:120])
    return achados


def auditar_redundancia_estrutural(tema, objeto, objetivo):
    """Detecta repetição quase literal; não tenta reescrever conteúdo material."""
    valores = {"tema": _normalizar(tema or ""), "objeto": _normalizar(objeto or ""), "objetivo": _normalizar(objetivo or "")}
    tokens = {k: set(re.findall(r"\b\w{4,}\b", v)) for k, v in valores.items()}
    achados = []
    for a, b in (("tema", "objeto"), ("tema", "objetivo"), ("objeto", "objetivo")):
        uniao = tokens[a] | tokens[b]
        similaridade = len(tokens[a] & tokens[b]) / len(uniao) if uniao else 0
        if valores[a] and (valores[a] == valores[b] or similaridade >= .8):
            achados.append({"tipo": "REDUNDANCIA_ESTRUTURAL", "severidade": "EDITORIAL", "campos": [a, b], "similaridade": round(similaridade, 3)})
    return achados

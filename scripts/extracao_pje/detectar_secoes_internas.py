"""Detecção conservadora de seções e anexos internos por títulos explícitos."""

import re

from .extrair_blocos_texto import proveniencia, referencia_pagina

PADROES = (
    (re.compile(r"^CONCLUS(?:ÃO|AO)\b", re.I), "CONCLUSAO"),
    (re.compile(r"^RELAT[ÓO]RIO\s+FOTOGR[ÁA]FICO\b", re.I), "RELATORIO_FOTOGRAFICO"),
    (re.compile(r"^(?:PLANILHA\s+)?OR[ÇC]AMENT[ÁA]RI[AO]\b|^OR[ÇC]AMENTO\b", re.I), "ORCAMENTO"),
    (re.compile(r"^MEM[ÓO]RIA\s+DE\s+C[ÁA]LCULO\b", re.I), "MEMORIA_CALCULO"),
    (re.compile(r"^REFER[ÊE]NCIAS\b", re.I), "REFERENCIAS"),
    (re.compile(r"^ANEXO\s+(?:[IVXLCDM]+|\d+)\b", re.I), "ANEXO"),
)


def detectar_secoes(paginas_texto, contexto):
    achados = []
    for pagina_pdf, pagina_documento, texto in paginas_texto:
        for linha in texto.splitlines():
            titulo = linha.strip()
            if not titulo or len(titulo) > 120:
                continue
            tipo = next((tipo for padrao, tipo in PADROES if padrao.search(titulo)), None)
            if tipo:
                if tipo == "ANEXO":
                    titulo_base = titulo.lower()
                    if "fotogr" in titulo_base:
                        tipo = "RELATORIO_FOTOGRAFICO"
                    elif "orçament" in titulo_base or "orcament" in titulo_base:
                        tipo = "ORCAMENTO"
                    elif "memória de cálculo" in titulo_base or "memoria de calculo" in titulo_base:
                        tipo = "MEMORIA_CALCULO"
                achado = (pagina_pdf, pagina_documento, titulo, tipo)
                if achado not in achados:
                    achados.append(achado)
    secoes = []
    for i, (pdf, interna, titulo, tipo) in enumerate(achados):
        proximo_pdf = max(pdf, achados[i + 1][0] - 1) if i + 1 < len(achados) else paginas_texto[-1][0]
        refs = [referencia_pagina(p, pd) for p, pd, _ in paginas_texto if pdf <= p <= proximo_pdf]
        secoes.append({"secao_id": f"SEC-{i+1:03d}", "titulo_original": titulo, "tipo_normalizado": tipo,
                       "pagina_inicio": refs[0], "pagina_fim": refs[-1], "paginas": refs, "texto": None,
                       "proveniencia": proveniencia(contexto, pdf, interna, titulo),
                       "confianca": {"nivel": "ALTA", "score": 0.9}})
    return secoes


def criar_subdocumentos(secoes, documento_id, paginas_documento):
    subdocumentos = []
    mapa = {"ANEXO": "ANEXO", "RELATORIO_FOTOGRAFICO": "RELATORIO_FOTOGRAFICO",
            "ORCAMENTO": "ORCAMENTO", "MEMORIA_CALCULO": "MEMORIA_CALCULO"}
    for secao in secoes:
        # Só títulos explicitamente anexados viram subdocumento. Seções comuns,
        # ainda que fotográficas/orçamentárias, permanecem apenas seções.
        titulo = secao["titulo_original"] or ""
        if not re.match(r"^ANEXO\b", titulo, re.I):
            continue
        refs = secao["paginas"]
        indices = {r["pagina_pdf"] for r in refs}
        recortes = [p for p in paginas_documento if p["referencia"]["pagina_pdf"] in indices]
        subdocumentos.append({"subdocumento_id": f"SUB-{len(subdocumentos)+1:03d}", "documento_pai": documento_id,
                              "titulo": titulo, "tipo": mapa.get(secao["tipo_normalizado"], "ANEXO"),
                              "pagina_inicio": refs[0], "pagina_fim": refs[-1], "paginas": refs,
                              "possui_texto": any(p["possui_texto_util"] for p in recortes),
                              "possui_imagens": any(p["possui_imagens"] for p in recortes),
                              "possui_tabelas": any(p["possui_tabelas"] for p in recortes),
                              "proveniencia": secao["proveniencia"]})
    return subdocumentos

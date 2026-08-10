"""Detecção de tabelas digitais sem interpretação técnica de valores."""

from .extrair_blocos_texto import bbox, proveniencia, referencia_pagina


def _tipo_tabela(texto):
    base = (texto or "").lower()
    if "orçamento" in base or "orcamento" in base or "preço unitário" in base:
        return "TABELA_ORCAMENTO"
    if "contrato" in base:
        return "TABELA_CONTRATUAL"
    if "alegaç" in base:
        return "TABELA_ALEGACOES"
    if "parecer técnico" in base or "parecer tecnico" in base:
        return "TABELA_PARECER_TECNICO"
    if "processo" in base:
        return "TABELA_PROCESSUAL"
    return "OUTRA"


def extrair_tabelas(leitor, pagina_pdf, pagina_documento, contexto, inicio):
    pagina = leitor.pagina_geometrica(pagina_pdf)
    texto_pagina = pagina.extract_text() or ""
    tabelas = []
    for deslocamento, tabela in enumerate(pagina.find_tables() or []):
        dados = tabela.extract() or []
        if not dados or not any(any((c or "").strip() for c in linha) for linha in dados):
            continue
        caixa = bbox(*tabela.bbox)
        bruto = "\n".join(" | ".join((c or "") for c in linha) for linha in dados)
        colunas = max((len(linha) for linha in dados), default=0)
        tabelas.append({"tabela_id": f"TAB-{inicio + deslocamento:03d}", "tipo": _tipo_tabela(texto_pagina),
                        "titulo": None, "texto_bruto": bruto, "estrutura_normalizada": dados,
                        "bbox": caixa, "linhas": len(dados), "colunas": colunas,
                        "dados_normalizados": dados, "pagina": referencia_pagina(pagina_pdf, pagina_documento),
                        "proveniencia": proveniencia(contexto, pagina_pdf, pagina_documento, bruto[:500], "TABELA_DIGITAL", "ALTA", caixa),
                        "confianca": {"nivel": "ALTA", "score": 0.9}})
    return tabelas

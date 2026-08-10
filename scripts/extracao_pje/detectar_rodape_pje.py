"""Detecção do rodapé estrutural inserido pelo PJe."""

import re

PADRAO_RODAPE = re.compile(r"Num\.\s*([0-9]+)\s*-\s*P[áa]g\.\s*([0-9]+)", re.I)


def detectar_rodape(texto: str, pagina_pdf: int) -> dict | None:
    encontrados = list(PADRAO_RODAPE.finditer(texto or ""))
    if not encontrados:
        return None
    achado = encontrados[-1]
    return {
        "id_pje": achado.group(1),
        "pagina_documento": int(achado.group(2)),
        "pagina_pdf": pagina_pdf,
        "texto_detectado": achado.group(0),
        "confianca": {"nivel": "ALTA", "score": 1.0},
    }

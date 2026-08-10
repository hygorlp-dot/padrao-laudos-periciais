"""Diagnóstico físico preliminar das páginas, sem executar OCR."""

from .detectar_rodape_pje import detectar_rodape


def diagnosticar_paginas(leitor):
    resultado = []
    for numero in range(1, leitor.total_paginas + 1):
        pagina = leitor.pagina_geometrica(numero)
        texto = pagina.extract_text() or ""
        rodape = detectar_rodape(texto, numero)
        imagens = len(pagina.images)
        area = max(float(pagina.width * pagina.height), 1.0)
        cobertura = min(1.0, sum(max(0, (i["x1"] - i["x0"]) * (i["bottom"] - i["top"])) for i in pagina.images) / area)
        chars = len(texto.strip())
        requer_ocr = chars < 30 and imagens > 0
        if chars == 0 and imagens == 0:
            classe = "PAGINA_EM_BRANCO"
        elif requer_ocr:
            classe = "DOCUMENTO_ESCANEADO"
        elif imagens and chars:
            classe = "TEXTO_E_IMAGEM"
        elif chars:
            classe = "TEXTO_DIGITAL"
        else:
            classe = "INDETERMINADA"
        resultado.append({
            "pagina_pdf": numero, "classificacao": classe, "quantidade_caracteres": chars,
            "densidade_textual": round(chars / area, 8), "quantidade_imagens": imagens,
            "cobertura_visual": round(cobertura, 6), "possui_rodape_pje": bool(rodape),
            "id_pje_detectado": rodape["id_pje"] if rodape else None,
            "pagina_documento_detectada": rodape["pagina_documento"] if rodape else None,
            "requer_inspecao_visual": requer_ocr, "requer_ocr": requer_ocr,
            "motivo_ocr": "Pouco texto digital e presença de imagem" if requer_ocr else None,
            "confianca": {"nivel": "ALTA" if rodape or chars >= 30 else "MEDIA"},
        })
    return resultado

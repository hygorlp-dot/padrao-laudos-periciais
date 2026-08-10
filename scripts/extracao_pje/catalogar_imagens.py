"""Catálogo geométrico de imagens incorporadas, sem OCR ou interpretação pericial."""

import re

from .extrair_blocos_texto import bbox, proveniencia, referencia_pagina

ROTULO_FOTO = re.compile(r"\b(Foto(?:grafia)?|Figura|FIG\.)\s*([0-9]+)?", re.I)


def catalogar_imagens(leitor, pagina_pdf, pagina_documento, contexto, inicio_imagem, inicio_foto):
    pagina = leitor.pagina_geometrica(pagina_pdf)
    texto = pagina.extract_text() or ""
    rotulo = ROTULO_FOTO.search(texto)
    imagens, fotos = [], []
    area_pagina = max(float(pagina.width * pagina.height), 1.0)
    for deslocamento, img in enumerate(pagina.images):
        caixa = bbox(img["x0"], img["top"], img["x1"], img["bottom"])
        largura, altura = float(img["x1"] - img["x0"]), float(img["bottom"] - img["top"])
        relevante = largura * altura / area_pagina >= 0.05
        tipo = "FOTOGRAFIA" if rotulo and relevante else "OUTRO"
        nivel, score = ("MEDIA", 0.8) if tipo == "FOTOGRAFIA" else ("BAIXA", 0.4)
        prov = proveniencia(contexto, pagina_pdf, pagina_documento, rotulo.group(0) if rotulo else None,
                           "CAMPO_ESTRUTURADO", nivel, caixa)
        imagens.append({"imagem_id": f"IMG-{inicio_imagem + deslocamento:03d}",
                        "pagina": referencia_pagina(pagina_pdf, pagina_documento), "bbox": caixa,
                        "tipo": tipo, "largura": largura, "altura": altura, "tipo_provavel": tipo,
                        "descricao": None, "proveniencia": prov, "confianca": {"nivel": nivel, "score": score}})
        if tipo == "FOTOGRAFIA":
            numero = rotulo.group(2) if rotulo else None
            fotos.append({"fotografia_id": f"FOT-{inicio_foto + len(fotos):03d}", "numero_original": numero,
                          "rotulo_original": rotulo.group(0) if rotulo else None, "legenda": None,
                          "pagina_pdf": pagina_pdf, "pagina_documento": pagina_documento, "pagina_original": None,
                          "bbox": caixa, "ambiente": None, "sistema": None, "descricao": None,
                          "data_hora": None, "coordenadas": None, "documento_pai": contexto["documento_id"],
                          "proveniencia": prov, "confianca": {"nivel": "MEDIA", "score": 0.8}})
    return imagens, fotos

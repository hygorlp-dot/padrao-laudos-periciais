"""Preservação do texto digital e criação de blocos rastreáveis por página."""


def referencia_pagina(pagina_pdf, pagina_documento):
    return {"pagina_pdf": pagina_pdf, "pagina_documento": pagina_documento, "pagina_original": None}


def bbox(x0, y0, x1, y1):
    return {"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1),
            "sistema_coordenadas": "PDFPLUMBER_TOPO_ESQUERDA", "unidade": "pt"}


def proveniencia(contexto, pagina_pdf, pagina_documento, trecho, metodo="TEXTO_DIGITAL", confianca="ALTA", caixa=None):
    p = {"arquivo": contexto["arquivo"], "sha256": contexto["sha256"], "documento_id": contexto["documento_id"],
         "id_pje": contexto["id_pje"], "pagina_pdf": pagina_pdf, "pagina_documento": pagina_documento,
         "pagina_original": None, "trecho": trecho, "natureza": "DOCUMENTADO", "metodo_extracao": metodo,
         "confianca": {"nivel": confianca}, "status_verificacao": "VERIFICADO"}
    if caixa is not None:
        p["bbox"] = caixa
    return p


def extrair_pagina_e_blocos(leitor, pagina_pdf, pagina_documento, contexto, inicio_bloco):
    pagina = leitor.pagina_geometrica(pagina_pdf)
    texto = pagina.extract_text() or ""
    palavras = pagina.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    blocos = []
    if palavras:
        caixa = bbox(min(w["x0"] for w in palavras), min(w["top"] for w in palavras),
                     max(w["x1"] for w in palavras), max(w["bottom"] for w in palavras))
        blocos.append({"bloco_id": f"BLT-{inicio_bloco:03d}", "texto": texto or " ", "bbox": caixa,
                       "ordem_leitura": inicio_bloco, "pagina": referencia_pagina(pagina_pdf, pagina_documento),
                       "proveniencia": proveniencia(contexto, pagina_pdf, pagina_documento, texto[:500] or None, caixa=caixa),
                       "confianca": {"nivel": "MEDIA", "score": 0.7}})
    return texto, blocos

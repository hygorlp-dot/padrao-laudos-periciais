"""Leitura de hyperlinks internos do índice por meio do pypdf."""


def _destino(objeto, mapa_paginas):
    try:
        destino = objeto.get("/Dest")
        if destino is None and objeto.get("/A"):
            destino = objeto["/A"].get_object().get("/D")
        if isinstance(destino, str):
            return None
        if destino:
            ref = destino[0]
            chave = getattr(ref, "idnum", None)
            return mapa_paginas.get(chave)
    except (AttributeError, KeyError, TypeError, IndexError):
        return None
    return None


def extrair_links_indice(leitor, paginas_indice):
    mapa = {getattr(p.indirect_reference, "idnum", None): i for i, p in enumerate(leitor.pypdf.pages, 1)}
    links = []
    for numero in paginas_indice:
        pagina_pdf = leitor.pypdf.pages[numero - 1]
        pagina_geo = leitor.pagina_geometrica(numero)
        for ref in pagina_pdf.get("/Annots", []):
            anotacao = ref.get_object()
            if anotacao.get("/Subtype") != "/Link":
                continue
            destino = _destino(anotacao, mapa)
            if not destino:
                continue
            rect = [float(v) for v in anotacao.get("/Rect", [])]
            texto = None
            if len(rect) == 4:
                x0, y0, x1, y1 = rect
                try:
                    texto = pagina_geo.crop((x0, pagina_geo.height - y1, x1, pagina_geo.height - y0)).extract_text() or None
                except ValueError:
                    texto = None
            links.append({"pagina_origem": numero, "pagina_destino": destino, "retangulo": rect or None, "texto_associado": texto})
    return links

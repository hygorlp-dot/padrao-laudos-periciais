"""Segmentação por sinais estruturais, sem regras específicas por processo."""


def segmentar_documentos(itens, paginas):
    total = len(paginas)
    inicios = {}
    for item in itens:
        if item.get("pagina_destino_link"):
            inicios[item["pagina_destino_link"]] = item
    for pagina in paginas:
        if pagina["possui_rodape_pje"] and pagina["pagina_documento_detectada"] == 1:
            item = next((i for i in itens if i["id_pje"] == pagina["id_pje_detectado"]), None)
            inicios.setdefault(pagina["pagina_pdf"], item)
    ordenados = sorted(inicios)
    documentos = []
    for pos, inicio in enumerate(ordenados):
        fim = ordenados[pos + 1] - 1 if pos + 1 < len(ordenados) else total
        item = inicios[inicio]
        rodapes = [p for p in paginas[inicio - 1:fim] if p["possui_rodape_pje"]]
        id_rodape = rodapes[0]["id_pje_detectado"] if rodapes else None
        id_pje = item["id_pje"] if item else id_rodape
        if not id_pje:
            continue
        ordem = item["ordem_indice"] if item else len(documentos) + 1
        documentos.append({"documento_id": f"DOC-PJE-{ordem:03d}", "id_pje": id_pje,
                           "pagina_pdf_inicio": inicio, "pagina_pdf_fim": fim, "total_paginas": fim - inicio + 1,
                           "item_indice": item, "id_rodape": id_rodape, "rodapes": rodapes})
    return documentos

"""Segmentação por sinais estruturais, sem regras específicas por processo."""


def segmentar_documentos(itens, paginas):
    total = len(paginas)
    inicios = {}
    for item in itens:
        if item.get("pagina_destino_link"):
            inicios.setdefault(item["pagina_destino_link"],[]).append(item)
    for pagina in paginas:
        if pagina["possui_rodape_pje"] and pagina["pagina_documento_detectada"] == 1:
            item = next((i for i in itens if i["id_pje"] == pagina["id_pje_detectado"]), None)
            if item is not None or pagina["pagina_pdf"] not in inicios:
                inicios.setdefault(pagina["pagina_pdf"],[]).append(item)
    for inicio, candidatos in list(inicios.items()):
        unicos={}
        for item in candidatos:
            chave=(item or {}).get("documento_id_interno") or (item or {}).get("id_pje") or "RODAPE"
            unicos[chave]=item
        inicios[inicio]=list(unicos.values())
    ordenados = sorted(inicios)
    documentos = []
    for pos, inicio in enumerate(ordenados):
        fim = ordenados[pos + 1] - 1 if pos + 1 < len(ordenados) else total
        candidatos=inicios[inicio];item=candidatos[0] if len(candidatos)==1 else None
        rodapes = [p for p in paginas[inicio - 1:fim] if p["possui_rodape_pje"]]
        id_rodape = rodapes[0]["id_pje_detectado"] if rodapes else None
        id_pje = item["id_pje"] if item else id_rodape
        if len(candidatos)>1:
            for colidido in sorted(candidatos,key=lambda x:(x["ordem_indice"],x["id_pje"])):
                documentos.append({"documento_id":colidido.get("documento_id_interno",f"DOC-PJE-{colidido['ordem_indice']:03d}"),"id_pje":colidido["id_pje"],"pagina_pdf_inicio":inicio,"pagina_pdf_fim":inicio,"total_paginas":1,"item_indice":colidido,"itens_colididos":candidatos,"id_rodape":id_rodape,"rodapes":rodapes,"estado_item_indice":"CONFLITO_DESTINO"})
            continue
        if not id_pje:continue
        ordem = item["ordem_indice"] if item else len(documentos) + 1
        documentos.append({"documento_id": f"DOC-PJE-{ordem:03d}", "id_pje": id_pje,
                           "pagina_pdf_inicio": inicio, "pagina_pdf_fim": fim, "total_paginas": fim - inicio + 1,
                           "item_indice": item, "id_rodape": id_rodape, "rodapes": rodapes,"estado_item_indice":"SEGMENTADO" if item else "DESCOBERTO_RODAPE"})
    return documentos

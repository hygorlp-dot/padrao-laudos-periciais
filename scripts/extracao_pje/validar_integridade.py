"""Regras relacionais que complementam o JSON Schema."""


def validar_integridade(manifesto):
    erros, alertas = [], []
    documentos = manifesto["documentos"]
    for item in manifesto["indice"]["itens"]:
        metodo=item.get("metodo_associacao_link")
        if metodo=="FALLBACK_POSICIONAL" and item.get("confianca",{}).get("nivel")=="ALTA":erros.append(f'{item.get("documento_id_interno")}: fallback posicional não pode ter confiança ALTA')
        if len(item.get("candidatos_destino_link",[]))>1 and item.get("destino_escolhido_link") is not None:erros.append(f'{item.get("documento_id_interno")}: associação ambígua não pode escolher destino')
        if item.get("pagina_destino_link")!=item.get("destino_escolhido_link"):erros.append(f'{item.get("documento_id_interno")}: destino escolhido diverge do destino de segmentação')
    ids = set()
    ocupadas = {}
    for doc in documentos:
        ident = doc["documento_id"]
        if doc["pagina_pdf_inicio"] > doc["pagina_pdf_fim"]:
            erros.append(f"{ident}: início posterior ao fim")
        esperado = doc["pagina_pdf_fim"] - doc["pagina_pdf_inicio"] + 1
        if doc["total_paginas"] != esperado:
            erros.append(f"{ident}: total de páginas inconsistente")
        if ident in ids:
            erros.append(f"{ident}: documento_id duplicado")
        ids.add(ident)
        for pagina in range(doc["pagina_pdf_inicio"], doc["pagina_pdf_fim"] + 1):
            if pagina in ocupadas:
                erros.append(f"Página {pagina} sobreposta por {ocupadas[pagina]} e {ident}")
            ocupadas[pagina] = ident
        rec = doc["status_reconciliacao"]
        if rec["status"] == "CONFIRMADO" and rec["id_indice"] and rec["id_rodape"] and rec["id_indice"] != rec["id_rodape"]:
            erros.append(f"{ident}: CONFIRMADO com IDs conflitantes")
        paginas = [p["pagina_documento_detectada"] for p in manifesto["paginas"][doc["pagina_pdf_inicio"]-1:doc["pagina_pdf_fim"]] if p["pagina_documento_detectada"] is not None]
        if paginas and paginas[0] != 1:
            alertas.append(f"{ident}: paginação interna começa em {paginas[0]}")
        if paginas and any(b != a + 1 for a, b in zip(paginas, paginas[1:])):
            erros.append(f"{ident}: salto na paginação interna {paginas}")
    met = manifesto["metricas_extracao"]
    itens={i["documento_id_interno"] for i in manifesto["indice"]["itens"] if i.get("documento_id_interno")}
    contabilizados={d.get("documento_id") for d in documentos if d.get("ordem_indice") is not None}
    contabilizados|={x for c in manifesto["conflitos"] for x in c.get("itens_indice_relacionados",[])}
    contabilizados|={x for p in manifesto.get("pendencias",[]) for x in p.get("itens_indice_relacionados",[])}
    faltantes=itens-{x for x in contabilizados if x}
    if faltantes: erros.append("Itens do índice não contabilizados: "+", ".join(sorted(faltantes)))
    if manifesto.get("status_validacao")=="VALIDADO" and (faltantes or manifesto.get("conflitos") or manifesto.get("pendencias")):erros.append("Status VALIDADO incompatível com item não contabilizado, conflito ou pendência")
    verificacoes = {"documentos_segmentados": len(documentos), "documentos_indice": len(manifesto["indice"]["itens"]),
                    "documentos_confirmados": sum(d["status_reconciliacao"]["status"] == "CONFIRMADO" for d in documentos),
                    "paginas_com_rodape": sum(p["possui_rodape_pje"] for p in manifesto["paginas"]),
                    "paginas_candidatas_ocr": sum(p["requer_ocr"] for p in manifesto["paginas"]),
                    "conflitos_abertos": len(manifesto["conflitos"])}
    for campo, valor in verificacoes.items():
        if met[campo] != valor:
            erros.append(f"Métrica {campo} inconsistente")
    if manifesto["processo"]["numero_cnj"]["proveniencia"]["pagina_pdf"] not in manifesto["indice"]["paginas"]:
        alertas.append("CNJ principal sem origem em página declarada do índice/capa")
    return erros, alertas

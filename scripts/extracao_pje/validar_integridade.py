"""Regras relacionais que complementam o JSON Schema."""


def _validar_itens_indice(manifesto, erros):
    for item in manifesto["indice"]["itens"]:
        metodo = item.get("metodo_associacao_link")
        if metodo == "FALLBACK_POSICIONAL" and item.get("confianca", {}).get("nivel") == "ALTA":
            erros.append(
                f'{item.get("documento_id_interno")}: fallback posicional não pode ter confiança ALTA'
            )
        if len(item.get("candidatos_destino_link", [])) > 1 and item.get("destino_escolhido_link") is not None:
            erros.append(
                f'{item.get("documento_id_interno")}: associação ambígua não pode escolher destino'
            )
        if item.get("pagina_destino_link") != item.get("destino_escolhido_link"):
            erros.append(
                f'{item.get("documento_id_interno")}: destino escolhido diverge do destino de segmentação'
            )


def _validar_documentos(manifesto, documentos, erros, alertas):
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
        if (
            rec["status"] == "CONFIRMADO"
            and rec["id_indice"]
            and rec["id_rodape"]
            and rec["id_indice"] != rec["id_rodape"]
        ):
            erros.append(f"{ident}: CONFIRMADO com IDs conflitantes")
        paginas = [
            pagina["pagina_documento_detectada"]
            for pagina in manifesto["paginas"][doc["pagina_pdf_inicio"] - 1 : doc["pagina_pdf_fim"]]
            if pagina["pagina_documento_detectada"] is not None
        ]
        if paginas and paginas[0] != 1:
            alertas.append(f"{ident}: paginação interna começa em {paginas[0]}")
        if paginas and any(b != a + 1 for a, b in zip(paginas, paginas[1:])):
            erros.append(f"{ident}: salto na paginação interna {paginas}")
    return ocupadas


def _validar_intervalos_de_owners(manifesto, ocupadas, erros):
    grupos = (
        ("conflito", manifesto.get("conflitos", [])),
        ("pendencia", manifesto.get("pendencias", [])),
    )
    for grupo_nome, grupo in grupos:
        for registro in grupo:
            if grupo_nome == "conflito" and registro.get("status") == "RESOLVIDO_POR_FONTE_PRIMARIA":
                continue
            if grupo_nome == "pendencia" and registro.get("status") != "ABERTA":
                continue
            inicio, fim = registro.get("pagina_pdf_inicio"), registro.get("pagina_pdf_fim")
            if inicio is None and fim is None:
                continue
            ident = registro.get("conflito_id") or registro.get("pendencia_id") or grupo_nome
            if not isinstance(inicio, int) or not isinstance(fim, int) or inicio > fim:
                erros.append(f"{ident}: intervalo de páginas inválido")
                continue
            if registro.get("total_paginas") != fim - inicio + 1:
                erros.append(f"{ident}: total de páginas inconsistente")
            for pagina in range(inicio, fim + 1):
                if pagina in ocupadas:
                    erros.append(f"Página {pagina} com owners incompatíveis: {ocupadas[pagina]} e {ident}")
                else:
                    ocupadas[pagina] = ident


def _validar_paginas_sem_owner(manifesto, ocupadas, erros):
    inicio_documental = max(manifesto.get("indice", {}).get("paginas", []) or [0]) + 1
    total_pdf = manifesto.get("arquivo", {}).get("total_paginas") or max(
        (pagina.get("pagina_pdf", 0) for pagina in manifesto.get("paginas", [])),
        default=0,
    )
    for pagina in range(inicio_documental, total_pdf + 1):
        if pagina not in ocupadas:
            erros.append(f"Página {pagina} sem owner na região documental")


def _contabilizar_itens_indice(manifesto, documentos, erros):
    itens = {
        item["documento_id_interno"]
        for item in manifesto["indice"]["itens"]
        if item.get("documento_id_interno")
    }
    contagens = {item: 0 for item in itens}
    for documento in documentos:
        if documento.get("ordem_indice") is not None and documento.get("documento_id") in contagens:
            contagens[documento["documento_id"]] += 1
    grupos = (
        ("conflito", manifesto["conflitos"]),
        ("pendencia", manifesto.get("pendencias", [])),
    )
    for tipo_grupo, grupo in grupos:
        for registro in grupo:
            if tipo_grupo == "conflito" and registro.get("status") == "RESOLVIDO_POR_FONTE_PRIMARIA":
                continue
            if tipo_grupo == "pendencia" and registro.get("status") != "ABERTA":
                continue
            for item in registro.get("itens_indice_relacionados", []):
                if item in contagens:
                    contagens[item] += 1
    faltantes = {item for item, total in contagens.items() if total == 0}
    duplicados = {item for item, total in contagens.items() if total > 1}
    if faltantes:
        erros.append("Itens do índice não contabilizados: " + ", ".join(sorted(faltantes)))
    if duplicados:
        erros.append("Itens do índice contabilizados mais de uma vez: " + ", ".join(sorted(duplicados)))
    return faltantes, duplicados


def _validar_status(manifesto, faltantes, duplicados, erros):
    if manifesto.get("status_validacao") == "VALIDADO" and (
        faltantes
        or duplicados
        or any(
            conflito.get("bloqueante") and conflito.get("status") == "ABERTO"
            for conflito in manifesto.get("conflitos", [])
        )
        or any(
            pendencia.get("bloqueante") and pendencia.get("status") == "ABERTA"
            for pendencia in manifesto.get("pendencias", [])
        )
    ):
        erros.append("Status VALIDADO incompatível com item não contabilizado, conflito ou pendência")


def _validar_metricas(manifesto, documentos, metricas, erros):
    verificacoes = {
        "documentos_segmentados": len(documentos),
        "documentos_indice": len(manifesto["indice"]["itens"]),
        "documentos_confirmados": sum(
            documento["status_reconciliacao"]["status"] == "CONFIRMADO" for documento in documentos
        ),
        "paginas_com_rodape": sum(pagina["possui_rodape_pje"] for pagina in manifesto["paginas"]),
        "paginas_candidatas_ocr": sum(pagina["requer_ocr"] for pagina in manifesto["paginas"]),
        "conflitos_abertos": len(manifesto["conflitos"]),
    }
    for campo, valor in verificacoes.items():
        if metricas[campo] != valor:
            erros.append(f"Métrica {campo} inconsistente")


def _alertar_origem_cnj(manifesto, alertas):
    if manifesto["processo"]["numero_cnj"]["proveniencia"]["pagina_pdf"] not in manifesto["indice"]["paginas"]:
        alertas.append("CNJ principal sem origem em página declarada do índice/capa")


def validar_integridade(manifesto):
    erros, alertas = [], []
    documentos = manifesto["documentos"]
    _validar_itens_indice(manifesto, erros)
    ocupadas = _validar_documentos(manifesto, documentos, erros, alertas)
    _validar_intervalos_de_owners(manifesto, ocupadas, erros)
    _validar_paginas_sem_owner(manifesto, ocupadas, erros)
    metricas = manifesto["metricas_extracao"]
    faltantes, duplicados = _contabilizar_itens_indice(manifesto, documentos, erros)
    _validar_status(manifesto, faltantes, duplicados, erros)
    _validar_metricas(manifesto, documentos, metricas, erros)
    _alertar_origem_cnj(manifesto, alertas)
    return erros, alertas

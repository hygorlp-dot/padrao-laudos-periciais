"""Reconciliação explícita dos sinais de índice, link e rodapé."""


def reconciliar_documento(documento):
    item = documento.get("item_indice")
    id_indice = item["id_pje"] if item else None
    id_rodape = documento.get("id_rodape")
    link = item.get("pagina_destino_link") if item else None
    motivos = []
    # O contrato reserva evidencias para objetos completos de proveniência.
    # Os sinais estruturais permanecem nos campos próprios da reconciliação.
    evidencias = []
    if id_indice and id_rodape and id_indice != id_rodape:
        status, nivel = "CONFLITANTE", "BAIXA"
        motivos.append("ID do índice diverge do ID do rodapé")
    elif id_indice and id_rodape:
        status, nivel = "CONFIRMADO", "ALTA"
    elif item and (link or id_rodape):
        status, nivel = "PROVAVEL", "MEDIA"
        motivos.append("Sinal estrutural complementar incompleto")
    elif item:
        status, nivel = "NAO_LOCALIZADO", "BAIXA"
        motivos.append("Item do índice sem página documental localizada")
    else:
        status, nivel = "SEM_ITEM_NO_INDICE", "MEDIA"
        motivos.append("Documento identificado apenas fora do índice")
    return {"status": status, "id_indice": id_indice, "id_rodape": id_rodape,
            "pagina_destino_link": link, "primeira_pagina_detectada": documento["pagina_pdf_inicio"],
            "ultima_pagina_detectada": documento["pagina_pdf_fim"], "evidencias": evidencias,
            "motivos": motivos, "confianca": {"nivel": nivel}}

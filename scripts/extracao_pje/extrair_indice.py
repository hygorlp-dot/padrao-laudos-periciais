"""Extração literal e auditável dos itens tabulares do índice PJe."""

import re
from datetime import datetime

from .normalizar_id_pje import normalizar_id_pje

DATA_HORA = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?")


def _limpar(valor):
    return (valor or "").strip()


def extrair_indice(leitor, paginas_indice, links):
    itens = []
    for pagina_numero in paginas_indice:
        pagina = leitor.pagina_geometrica(pagina_numero)
        destinos_ordenados = []
        for link in links:
            if link["pagina_origem"] == pagina_numero and link["pagina_destino"] not in destinos_ordenados:
                destinos_ordenados.append(link["pagina_destino"])
        ordem_na_pagina = 0
        for tabela in pagina.extract_tables() or []:
            for linha in tabela:
                celulas = [_limpar(c) for c in (linha or [])]
                if len(celulas) < 3:
                    continue
                try:
                    norm = normalizar_id_pje(celulas[0])
                except ValueError:
                    continue
                data_hora = DATA_HORA.search(" ".join(celulas[1:3]))
                if not data_hora:
                    continue
                preenchidas = [(i, c) for i, c in enumerate(celulas[2:], 2) if c]
                if len(preenchidas) < 2:
                    continue
                tipo = preenchidas[-1][1]
                titulo = " ".join(c for _, c in preenchidas[:-1]).strip()
                # Um ID quebrado em duas linhas costuma gerar dois retângulos de
                # link com o mesmo destino. A associação agrupa os textos pelo
                # destino antes de comparar, sem depender da posição da linha.
                por_destino = {}
                for link in links:
                    if link["pagina_origem"] == pagina_numero:
                        por_destino.setdefault(link["pagina_destino"], "")
                        por_destino[link["pagina_destino"]] += link.get("texto_associado") or ""
                candidatos = [d for d, texto in por_destino.items()
                              if norm["valor_normalizado"] in re.sub(r"\D+", "", texto)]
                if len(candidatos) == 1:
                    destino, metodo, nivel, score = candidatos[0], "LINK_ID_INEQUIVOCO", "ALTA", 1.0
                elif len(candidatos) > 1:
                    destino, metodo, nivel, score = None, "LINK_AMBIGUO", "BAIXA", 0.2
                elif ordem_na_pagina < len(destinos_ordenados):
                    destino, metodo, nivel, score = destinos_ordenados[ordem_na_pagina], "FALLBACK_POSICIONAL", "MEDIA", 0.6
                else:
                    destino, metodo, nivel, score = None, "SEM_ASSOCIACAO", "BAIXA", 0.0
                ordem_na_pagina += 1
                data = datetime.strptime(data_hora.group(1), "%d/%m/%Y").date().isoformat()
                hora = data_hora.group(2)
                if hora and len(hora) == 5:
                    hora += ":00"
                ordem = len(itens) + 1
                itens.append({
                    "documento_id_interno": f"DOC-PJE-{ordem:03d}", "id_pje": norm["valor_normalizado"],
                    "data": data, "hora": hora, "titulo_original": titulo, "tipo_original": tipo,
                    "ordem_indice": ordem, "pagina_destino_link": destino,
                    "pagina_origem_indice": pagina_numero, "metodo_associacao_link": metodo,
                    "candidatos_destino_link": sorted(candidatos), "destino_escolhido_link": destino,
                    "texto_bruto": " | ".join(celulas), "normalizacao_id": norm,
                    "confianca": {"nivel": nivel, "score": score},
                })
    return itens

"""Extração determinística de campos da capa inicial do PJe."""

import re

CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")


def _prov(leitor, pagina, trecho, encontrado=True):
    return {"arquivo": leitor.caminho.name, "sha256": leitor.sha256, "documento_id": None, "id_pje": None,
            "pagina_pdf": pagina, "pagina_documento": None, "pagina_original": None, "trecho": trecho,
            "natureza": "DOCUMENTADO" if encontrado else "INCONCLUSIVO", "metodo_extracao": "CAMPO_ESTRUTURADO",
            "confianca": {"nivel": "ALTA" if encontrado else "BAIXA"},
            "status_verificacao": "VERIFICADO" if encontrado else "INCONCLUSIVO"}


def _campo(leitor, texto, rotulos, pagina=1):
    for rotulo in rotulos:
        m = re.search(rf"{rotulo}\s*:?\s*([^\n|]+)", texto, re.I)
        if m and m.group(1).strip():
            valor = m.group(1).strip()
            return {"valor": valor, "motivo_ausencia": None, "proveniencia": _prov(leitor, pagina, m.group(0))}
    return {"valor": None, "motivo_ausencia": "NAO_LOCALIZADO", "proveniencia": _prov(leitor, pagina, None, False)}


def _flag(leitor, texto, rotulo):
    m = re.search(rf"{rotulo}\s*:?\s*(SIM|N[ÃA]O|NÃO|NAO)", texto, re.I)
    if not m:
        return {"valor": None, "motivo_ausencia": "NAO_LOCALIZADO", "proveniencia": _prov(leitor, 1, None, False)}
    return {"valor": m.group(1).upper() == "SIM", "motivo_ausencia": None, "proveniencia": _prov(leitor, 1, m.group(0))}


def extrair_capa(leitor, paginas_iniciais):
    textos = [(p, leitor.texto(p)) for p in paginas_iniciais]
    combinado = "\n".join(t for _, t in textos)
    cnj = CNJ.search(combinado)
    numero = cnj.group(0) if cnj else "0000000-00.0000.0.00.0000"
    pagina_cnj = next((p for p, t in textos if numero in t), 1)
    valor_match = re.search(r"Valor\s+da\s+causa\s*:?\s*R\$\s*([\d\.]+,\d{2})", combinado, re.I)
    valor = float(valor_match.group(1).replace(".", "").replace(",", ".")) if valor_match else None
    valor_causa = {"valor": valor, "moeda": "BRL" if valor is not None else None,
                   "motivo_ausencia": None if valor is not None else "NAO_LOCALIZADO",
                   "proveniencia": _prov(leitor, 1, valor_match.group(0) if valor_match else None, bool(valor_match))}
    assuntos = []
    campo_assunto = _campo(leitor, combinado, ["Assunto(?:s)?"])
    if campo_assunto["valor"]:
        assuntos = [campo_assunto]
    ultima = _campo(leitor, combinado, ["Última Distribuição", "Ultima Distribuicao"])
    return {
        "processo": {
            "numero_cnj": {"valor": numero, "proveniencia": _prov(leitor, pagina_cnj, numero if cnj else None, bool(cnj))},
            "tribunal": _campo(leitor, combinado, ["Tribunal"]), "secao": _campo(leitor, combinado, ["Seção", "Secao"]),
            "subsecao": _campo(leitor, combinado, ["Subseção", "Subsecao"]),
            "orgao_julgador": _campo(leitor, combinado, ["Órgão julgador", "Orgao julgador"]),
            "classe": _campo(leitor, combinado, ["Classe judicial", "Classe"]), "assuntos": assuntos,
            "valor_causa": valor_causa,
            "flags": {"segredo_justica": _flag(leitor, combinado, "Segredo de justiça"),
                      "justica_gratuita": _flag(leitor, combinado, "Justiça gratuita"),
                      "pedido_liminar": _flag(leitor, combinado, "Pedido liminar")},
        },
        "ultima_distribuicao": ultima,
        "cnj_localizado": bool(cnj),
    }

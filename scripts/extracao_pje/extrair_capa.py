"""Extração determinística de campos da capa inicial do PJe."""

import re

CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")


def _prov(leitor, pagina, trecho, encontrado=True):
    return {"arquivo": leitor.caminho.name, "sha256": leitor.sha256, "documento_id": None, "id_pje": None,
            "pagina_pdf": pagina, "pagina_documento": None, "pagina_original": None, "trecho": trecho,
            "natureza": "DOCUMENTADO" if encontrado else "INCONCLUSIVO", "metodo_extracao": "CAMPO_ESTRUTURADO",
            "confianca": {"nivel": "ALTA" if encontrado else "BAIXA"},
            "status_verificacao": "VERIFICADO" if encontrado else "INCONCLUSIVO"}


def _campo(leitor, textos, rotulos):
    achados=[]
    for pagina,texto in textos:
      for rotulo in rotulos:
        m = re.search(rf"{rotulo}\s*:?\s*([^\n|]+)", texto, re.I)
        if m and m.group(1).strip():achados.append((m.group(1).strip(),pagina,m.group(0)))
    distintos={a[0] for a in achados}
    if len(distintos)>1:return {"valor":None,"motivo_ausencia":None,"status":"CONFLITANTE","fontes":[_prov(leitor,p,t) for _,p,t in achados],"proveniencia":_prov(leitor,achados[0][1],achados[0][2])}
    if achados:
        valor,pagina,trecho=achados[0];return {"valor":valor,"motivo_ausencia":None,"proveniencia":_prov(leitor,pagina,trecho)}
    return {"valor":None,"motivo_ausencia":"NAO_LOCALIZADO","proveniencia":_prov(leitor,None,None,False)}


def _flag(leitor, textos, rotulo):
    achados=[(p,re.search(rf"{rotulo}\s*:?\s*(SIM|N[ÃA]O|NÃO|NAO)",t,re.I)) for p,t in textos];achados=[x for x in achados if x[1]]
    m=achados[0][1] if achados else None
    if not m:
        return {"valor": None, "motivo_ausencia": "NAO_LOCALIZADO", "proveniencia": _prov(leitor, None, None, False)}
    return {"valor": m.group(1).upper() == "SIM", "motivo_ausencia": None, "proveniencia": _prov(leitor, achados[0][0], m.group(0))}


def extrair_capa(leitor, paginas_iniciais):
    textos = [(p, leitor.texto(p)) for p in paginas_iniciais]
    combinado = "\n".join(t for _, t in textos)
    cnj = CNJ.search(combinado)
    numero = cnj.group(0) if cnj else "0000000-00.0000.0.00.0000"
    pagina_cnj = next((p for p, t in textos if cnj and numero in t), None)
    valor_achados=[(p,re.search(r"Valor\s+da\s+causa\s*:?\s*R\$\s*([\d\.]+,\d{2})",t,re.I)) for p,t in textos]
    valor_achados=[x for x in valor_achados if x[1]]
    valor_match = valor_achados[0][1] if valor_achados else None
    valor = float(valor_match.group(1).replace(".", "").replace(",", ".")) if valor_match else None
    valor_causa = {"valor": valor, "moeda": "BRL" if valor is not None else None,
                   "motivo_ausencia": None if valor is not None else "NAO_LOCALIZADO",
                   "proveniencia": _prov(leitor, valor_achados[0][0] if valor_achados else None, valor_match.group(0) if valor_match else None, bool(valor_match))}
    assuntos = []
    campo_assunto = _campo(leitor, textos, ["Assunto(?:s)?"])
    if campo_assunto["valor"]:
        assuntos = [campo_assunto]
    ultima = _campo(leitor, textos, ["Última Distribuição", "Ultima Distribuicao"])
    return {
        "processo": {
            "numero_cnj": {"valor": numero, "proveniencia": _prov(leitor, pagina_cnj, numero if cnj else None, bool(cnj))},
            "tribunal": _campo(leitor, textos, ["Tribunal"]), "secao": _campo(leitor, textos, ["Seção", "Secao"]),
            "subsecao": _campo(leitor, textos, ["Subseção", "Subsecao"]),
            "orgao_julgador": _campo(leitor, textos, ["Órgão julgador", "Orgao julgador"]),
            "classe": _campo(leitor, textos, ["Classe judicial", "Classe"]), "assuntos": assuntos,
            "valor_causa": valor_causa,
            "flags": {"segredo_justica": _flag(leitor, textos, "Segredo de justiça"),
                      "justica_gratuita": _flag(leitor, textos, "Justiça gratuita"),
                      "pedido_liminar": _flag(leitor, textos, "Pedido liminar")},
        },
        "ultima_distribuicao": ultima,
        "cnj_localizado": bool(cnj),
    }

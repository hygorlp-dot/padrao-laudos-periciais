"""Validação JSON Schema e integridade relacional de DOCUMENTO_PJE."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def criar_validador(raiz_repositorio=None):
    raiz = Path(raiz_repositorio or Path(__file__).resolve().parents[2])
    nomes = ("pje-comum.schema.json", "documento-pje.schema.json")
    schemas = [json.loads((raiz / "schemas" / n).read_text(encoding="utf-8")) for n in nomes]
    registro = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    return Draft202012Validator(schemas[1], registry=registro)


def validar_documento(documento, documento_manifesto, validador=None):
    erros, alertas = [], []
    validador = validador or criar_validador()
    for erro in sorted(validador.iter_errors(documento), key=lambda e: list(e.path)):
        erros.append(f"schema:{'/'.join(map(str, erro.path))}: {erro.message}")
    for campo in ("documento_id", "id_pje"):
        if documento[campo] != documento_manifesto[campo]:
            erros.append(f"{campo} diverge do manifesto")
    for campo in ("titulo_original", "tipo_original", "ordem_indice", "data_hora", "status_reconciliacao"):
        if campo in documento_manifesto and documento[campo] != documento_manifesto[campo]:
            erros.append(f"{campo} diverge do manifesto")
    processo_cnj = documento_manifesto.get("_processo_cnj")
    if processo_cnj is not None and documento["processo_cnj"] != processo_cnj:
        erros.append("processo_cnj diverge do manifesto")
    inicio, fim = documento_manifesto["pagina_pdf_inicio"], documento_manifesto["pagina_pdf_fim"]
    paginas = [p["referencia"]["pagina_pdf"] for p in documento["paginas"]]
    if paginas != list(range(inicio, fim + 1)):
        erros.append("páginas não correspondem integralmente ao intervalo do manifesto")
    if not paginas or paginas[0] != inicio or paginas[-1] != fim:
        erros.append("primeira ou última página diverge do manifesto")
    internas = {p["referencia"]["pagina_pdf"]: p["referencia"]["pagina_documento"] for p in documento["paginas"]}
    for colecao, chave in (("blocos_texto", "pagina"), ("tabelas", "pagina"), ("imagens", "pagina")):
        for objeto in documento[colecao]:
            pagina = objeto[chave]["pagina_pdf"]
            if pagina not in internas:
                erros.append(f"{colecao}: objeto aponta para página externa {pagina}")
    for foto in documento["fotografias"]:
        if foto["pagina_pdf"] not in internas:
            erros.append(f"fotografias: objeto aponta para página externa {foto['pagina_pdf']}")
    for imagem in documento["imagens"]:
        proveniencia_imagem = imagem.get("proveniencia")
        pagina_imagem = imagem.get("pagina")
        if not isinstance(proveniencia_imagem, dict) or not isinstance(pagina_imagem, dict):
            continue
        if proveniencia_imagem.get("bbox") != imagem.get("bbox"):
            erros.append(f"{imagem.get('imagem_id', 'imagem')}: bbox diverge da proveniencia")
        if (
            proveniencia_imagem.get("pagina_pdf") != pagina_imagem.get("pagina_pdf")
            or proveniencia_imagem.get("pagina_documento") != pagina_imagem.get("pagina_documento")
            or proveniencia_imagem.get("pagina_original") != pagina_imagem.get("pagina_original")
        ):
            erros.append(f"{imagem.get('imagem_id', 'imagem')}: pagina diverge da proveniencia")
    for secao in documento["secoes"]:
        if "id_pje" in secao:
            erros.append(f"{secao['secao_id']}: seção interna não pode possuir id_pje")
        if any(p["pagina_pdf"] not in internas for p in secao["paginas"]):
            erros.append(f"{secao['secao_id']}: seção aponta para página externa")
    for sub in documento["subdocumentos"]:
        if sub["documento_pai"] != documento["documento_id"]:
            erros.append(f"{sub['subdocumento_id']}: documento_pai divergente")
        if any(p["pagina_pdf"] not in internas for p in sub["paginas"]):
            erros.append(f"{sub['subdocumento_id']}: subdocumento aponta para página externa")
    for pagina in documento["paginas"]:
        pdf = pagina["referencia"]["pagina_pdf"]
        esperado = next((p["pagina_documento_detectada"] for p in documento_manifesto.get("_paginas_manifesto", []) if p["pagina_pdf"] == pdf), None)
        if esperado is not None and pagina["referencia"]["pagina_documento"] != esperado:
            erros.append(f"página {pdf}: pagina_documento diverge do rodapé PJe")
    if documento["classe_normalizada"] == "OUTRO" or documento.get("status_revisao") == "PENDENTE_REVISAO":
        alertas.append("classificação requer revisão humana")
    return erros, alertas

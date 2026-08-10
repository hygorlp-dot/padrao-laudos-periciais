"""Extrai candidatos a quesito preservando texto e proveniência do documento PJe."""

from __future__ import annotations

import re
from typing import Any


INICIO = re.compile(r"(?im)^\s*(?:quesitos?(?:\s+da\s+[^\n:]+)?|dos\s+quesitos)\s*:?[ \t]*$")
ITEM = re.compile(
    r"(?ms)^\s*(?P<num>\d{1,3})\s*[.)-]\s*(?P<texto>.+?)"
    r"(?=^\s*\d{1,3}\s*[.)-]\s+|^\s*(?:nestes termos|por fim|assinado eletronicamente|termos em que)|\Z)"
)
INDICADORES = re.compile(
    r"(?i)(?:\?|queira|informe|esclare[çc]a|descreva|poderia|considerando|"
    r"qual|quais|como|havia|houve|existe|existia|o im[oó]vel|a rodovia|o local)"
)


def _proveniencia(documento: dict[str, Any], pagina: dict[str, Any], trecho: str) -> dict[str, Any]:
    base = None
    for bloco in documento.get("blocos_texto", []):
        if bloco["pagina"]["pagina_pdf"] == pagina["referencia"]["pagina_pdf"]:
            base = bloco["proveniencia"]
            break
    if base is None:
        raise ValueError(f"Documento {documento['documento_id']} sem proveniência textual")
    resultado = {chave: valor for chave, valor in base.items() if chave != "bbox"}
    resultado["trecho"] = trecho[:500]
    return resultado


def extrair(documentos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrai todos os candidatos reconhecíveis; casos ambíguos ficam para revisão semântica."""
    candidatos: list[dict[str, Any]] = []
    vistos: set[tuple[str, str]] = set()
    for documento in documentos:
        paginas = documento.get("paginas", [])
        texto = "\n".join(pagina.get("texto_bruto", "") for pagina in paginas)
        titulo = documento.get("titulo_original", "").lower()
        classe = documento.get("classe_normalizada", "")
        contexto = texto.lower()
        submissao_explicita = bool(re.search(r"(?:apresenta|apresentar|junta|formular)\w*\s+(?:os\s+|seus\s+)?quesitos", contexto))
        decisao_com_quesitos = classe in {"DECISAO", "DESPACHO"} and bool(
            re.search(r"quesitos?\s+(?:do\s+ju[ií]zo|a\s+serem\s+respondidos|abaixo|seguintes)", contexto)
        )
        origem_plausivel = submissao_explicita or decisao_com_quesitos or "quesit" in titulo or bool(INICIO.search(texto))
        if not origem_plausivel:
            continue
        inicios = list(INICIO.finditer(texto))
        if not inicios and "quesit" not in texto.lower():
            continue
        recorte = texto[inicios[0].end():] if inicios else texto
        for item in ITEM.finditer(recorte):
            numero = item.group("num")
            integral = item.group("texto").strip()
            integral = re.split(r"Assinado eletronicamente por:|https?://|Número do documento:", integral)[0].strip()
            if len(integral) < 12 or len(integral) > 2500 or not INDICADORES.search(integral):
                continue
            chave = (documento["documento_id"], re.sub(r"\W+", "", integral).lower())
            if chave in vistos:
                continue
            vistos.add(chave)
            pagina_encontrada = next(
                (pagina for pagina in paginas if integral[:30].lower() in re.sub(r"\s+", " ", pagina.get("texto_bruto", "")).lower()),
                paginas[0],
            )
            candidatos.append({
                "documento_id": documento["documento_id"], "id_pje": documento["id_pje"],
                "numero_original": numero, "texto_integral": integral,
                "pagina": pagina_encontrada["referencia"],
                "proveniencia": _proveniencia(documento, pagina_encontrada, integral),
            })
    return candidatos

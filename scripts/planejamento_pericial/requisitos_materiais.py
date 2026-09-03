"""Extração determinística de requisitos materiais de um quesito.

O texto do quesito NÃO é autoridade de cobertura: aqui ele é apenas segmentado,
com identidade e proveniência estáveis, em requisitos materiais estruturados e
classificados por natureza. A cobertura é decidida a jusante por vínculo
estruturado a um item planejado de tipo apropriado (ver validar_plano).

Classificação (natureza do requisito), por vocabulário técnico bounded e
documentado em docs/padroes/padrao-planejamento-vistoria.md:
- MEDICAO   — exige leitura instrumental / ensaio / cálculo. Sinalizada por verbo
  de medição, por grandeza inerentemente dimensional, ou por marcador de
  quantificação sobre grandeza quantificável.
- DOCUMENTO — exige obtenção/análise documental (verbo documental + artefato).
- INSPECAO  — satisfazível por observação de campo. É o default apenas quando
  nenhum sinal de MEDICAO/DOCUMENTO está presente.
"""

from __future__ import annotations

import hashlib
import re

from scripts.triagem_pericial.semantica import normalizar, termos

# Ruído estrutural reconhecido por FORMATO, nunca por valores concretos do caso.
_RUIDO = [
    re.compile(r"(?im)\bn(?:um|º|o)\.?\s*\d+\s*[-–—]\s*p[áa]g(?:ina)?\.?\s*\d+\b"),
    re.compile(r"(?im)^\s*p[áa]gina\s+complementar\b.*$"),
    re.compile(r"(?im)^\s*(?:f?ls?\.?|folhas?)\s*\d+.*$"),
    re.compile(r"(?im)\bn[úu]mero\s+do\s+documento:.*$"),
    re.compile(r"(?im)\bassinado\s+eletronicamente\b.*$"),
    re.compile(r"https?://\S+"),
    re.compile(r"(?im)^\s*[\d\W_]+\s*$"),
]
_VERBO_TECNICO = re.compile(
    r"(?i)\b(?:verificar|avaliar|analis\w+|estimar|medir|caracterizar|quantificar|"
    r"constatar|identificar|localizar|classificar|determinar|apurar|aferir|mensurar|"
    r"dimensionar|calcular|conferir|inspecionar|documentar|descrever|registrar|"
    r"ensaiar|testar|examinar|observar|solicitar|juntar|apresentar|requisitar)\b"
)
# " e "/"," só separam quando o lado seguinte também abre uma instrução técnica.
_SEPARADOR_FORTE = re.compile(r"(?:[.;?!]+\s+)|(?:\s*\n[-–—•]\s+)|(?:\s*\n\s*\d{1,2}\s*[.)]\s+)")
_CONECTOR = re.compile(r"\s*(?:,|;|\se\s|\seou\s|\sou\s)\s*")

_VERBO_MEDICAO = re.compile(r"(?i)\b(?:medir|medi[cç][aã]o|aferir|mensurar|quantificar|dimensionar|calcular|c[aá]lcul[oa]|ensai\w+|testar\s+(?:a\s+)?(?:carga|resist|press))\b")
_GRANDEZA_DIMENSIONAL = re.compile(
    r"(?i)\b(?:espessura|recalque|flecha|prumo|aprumo|desaprumo|desvio\s+de\s+prumo|"
    r"nivelamento|desn[íi]vel|inclina[cç][aã]o|caimento|declividade|deforma[cç][aã]o|"
    r"deslocamento|esquadr\w+|dimens\w+|[aá]rea|volume|cota|dist[aâ]ncia|[aâ]ngulo|"
    r"largura|altura|comprimento|profundidade|abertura\s+d[ae]s?\s+(?:fissur|trinc)|"
    r"vaz[aã]o|carga|tens[aã]o\s+atuante|umidade\s+relativa)\b"
)
_QUANTIFICADOR = re.compile(r"(?i)\b(?:teor|[íi]ndice|n[íi]vel|grau|percentual|coeficiente|taxa)\s+d[eo]\b")
_GRANDEZA_QUANTIFICAVEL = re.compile(r"(?i)\b(?:umidade|temperatura|resist[eê]ncia|press[aã]o|dureza|pH|cloret\w+|carbonata[cç]\w+)\b")
_DOC_VERBO = re.compile(r"(?i)\b(?:solicitar|requisitar|juntar|apresentar|obter|anexar)\b")
_DOC_ARTEFATO = re.compile(r"(?i)\b(?:documento|projeto|memorial|planta|art\b|rrt\b|laudo|contrato|nota\s+fiscal|as\s*built|caderno|especifica[cç][aã]o\s+t[eé]cnica|habite-se|alvar[aá])\b")

_MIN_TERMOS = 1


def remover_ruido_estrutural(texto: str) -> str:
    limpo = str(texto or "")
    for padrao in _RUIDO:
        limpo = padrao.sub(" ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def classificar_requisito(texto: str) -> str:
    """MEDICAO | DOCUMENTO | INSPECAO — determinística, fail-closed (na dúvida entre
    observar e medir uma grandeza dimensional, exige MEDICAO)."""
    base = " " + normalizar(texto) + " "
    if _VERBO_MEDICAO.search(base) or _GRANDEZA_DIMENSIONAL.search(base) or (
        _QUANTIFICADOR.search(base) and _GRANDEZA_QUANTIFICAVEL.search(base)
    ):
        return "MEDICAO"
    if _DOC_VERBO.search(base) and _DOC_ARTEFATO.search(base):
        return "DOCUMENTO"
    return "INSPECAO"


def _identidade(quesito_id: str, texto: str) -> str:
    numero = quesito_id.split("-")[-1]
    base = " ".join(sorted(termos(texto))) or normalizar(texto)
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8].upper()
    return f"REQ-{numero}-{digest}"


def _norma_exibicao(fragmento: str) -> str:
    return re.sub(r"^\W+|\W+$", "", normalizar(fragmento)).strip()


def _segmentar(texto_limpo: str) -> list[str]:
    brutos = [p.strip(" \t\n-–—•,;") for p in _SEPARADOR_FORTE.split(texto_limpo) if p and p.strip(" \t\n-–—•,;")]
    fragmentos: list[str] = []
    for bruto in brutos:
        partes = _CONECTOR.split(bruto)
        atual = partes[0].strip() if partes else ""
        for cont in partes[1:]:
            cont = cont.strip()
            # só quebra se o lado seguinte também abre uma instrução técnica própria
            if cont and _VERBO_TECNICO.match(cont):
                if atual:
                    fragmentos.append(atual)
                atual = cont
            else:
                atual = f"{atual}, {cont}".strip(", ") if atual else cont
        if atual:
            fragmentos.append(atual)
    saneados: list[str] = []
    for parte in fragmentos:
        if len(parte) < 8 or len(termos(parte)) < _MIN_TERMOS:
            if saneados:
                saneados[-1] = f"{saneados[-1]} {parte}".strip()
            continue
        saneados.append(parte)
    return saneados or ([texto_limpo] if texto_limpo else [])


def extrair_requisitos_materiais(quesito: dict) -> list[dict]:
    """Requisitos materiais estruturados de um quesito pertinente.

    Cada item: requirement_id, quesito, requisito (cláusula-fonte), texto_normalizado,
    classe (MEDICAO|DOCUMENTO|INSPECAO), proveniencia, status ∈ {MATERIAL, EXTRACAO_INDETERMINADA}.
    Fail-closed: quesito pertinente cujo texto não produz cláusula material rende um
    requisito EXTRACAO_INDETERMINADA (nunca zero silencioso).
    """
    quesito_id = quesito["id"]
    proveniencia = quesito.get("proveniencia") or quesito.get("paginas") or []
    fontes = [str(x) for x in quesito.get("subitens", []) if str(x).strip()]
    if not fontes:
        bruto = quesito.get("materia_tecnica") or quesito.get("texto_integral") or ""
        fontes = [str(bruto)] if str(bruto).strip() else []
    requisitos: list[dict] = []
    vistos: set[str] = set()
    for fonte in fontes:
        for fragmento in _segmentar(remover_ruido_estrutural(fonte)):
            rid = _identidade(quesito_id, fragmento)
            if rid in vistos:
                continue
            vistos.add(rid)
            requisitos.append({
                "requirement_id": rid, "quesito": quesito_id, "requisito": fragmento,
                "texto_normalizado": _norma_exibicao(fragmento), "classe": classificar_requisito(fragmento),
                "proveniencia": proveniencia, "status": "MATERIAL",
            })
    if not requisitos:
        norma = _norma_exibicao(remover_ruido_estrutural(" ".join(fontes)))
        requisitos.append({
            "requirement_id": _identidade(quesito_id, norma or quesito_id),
            "quesito": quesito_id, "requisito": (" ".join(fontes)).strip() or quesito_id,
            "texto_normalizado": norma, "classe": "INSPECAO", "proveniencia": proveniencia,
            "status": "EXTRACAO_INDETERMINADA",
        })
    return requisitos

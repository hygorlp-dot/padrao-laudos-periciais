"""Extração determinística de requisitos materiais de um quesito.

O texto do quesito NÃO é autoridade de cobertura: aqui ele é apenas segmentado,
com identidade e proveniência estáveis, em requisitos materiais estruturados. A
cobertura é decidida a jusante por vínculo explícito (ver validar_plano).
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
_SEPARADOR = re.compile(r"(?:[.;?!]+\s+)|(?:\s*\n[-–—•]\s+)|(?:\s*\n\s*\d{1,2}\s*[.)]\s+)|(?:\s+e\s+(?=[a-zç]))")
_VERBO_TECNICO = re.compile(
    r"(?i)\b(?:verificar|avaliar|analis\w+|estimar|medir|caracterizar|"
    r"quantificar|constatar|identificar|classificar|determinar|apurar|"
    r"conferir|inspecionar|documentar|registrar|ensaiar|calcular|examinar)\b"
)
_MIN_TERMOS = 1


def remover_ruido_estrutural(texto: str) -> str:
    limpo = str(texto or "")
    for padrao in _RUIDO:
        limpo = padrao.sub(" ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def _identidade(quesito_id: str, texto: str) -> str:
    """Identidade estável por conjunto de termos de conteúdo: invariante à ordem
    das cláusulas e à pontuação de borda; cláusulas distintas em conteúdo material
    recebem ids distintos."""
    numero = quesito_id.split("-")[-1]
    base = " ".join(sorted(termos(texto))) or normalizar(texto)
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8].upper()
    return f"REQ-{numero}-{digest}"


def _norma_exibicao(fragmento: str) -> str:
    return re.sub(r"^\W+|\W+$", "", normalizar(fragmento)).strip()


def _segmentar(texto_limpo: str) -> list[str]:
    partes = [p.strip(" \t\n-–—•,;") for p in _SEPARADOR.split(texto_limpo) if p and p.strip(" \t\n-–—•,;")]
    fragmentos: list[str] = []
    for parte in partes:
        if len(parte) < 8:
            if fragmentos:
                fragmentos[-1] = f"{fragmentos[-1]} {parte}".strip()
            continue
        fragmentos.append(parte)
    return fragmentos or ([texto_limpo] if texto_limpo else [])


def _material(fragmento: str) -> bool:
    return len(termos(fragmento)) >= _MIN_TERMOS


def extrair_requisitos_materiais(quesito: dict) -> list[dict]:
    """Retorna requisitos materiais estruturados de um quesito pertinente.

    Cada item: requirement_id, quesito, requisito (cláusula-fonte), texto_normalizado,
    proveniencia, status ∈ {MATERIAL, EXTRACAO_INDETERMINADA}.
    Fail-closed: quesito pertinente cujo texto não produz nenhuma cláusula material
    rende um requisito EXTRACAO_INDETERMINADA (nunca zero silencioso).
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
        limpo = remover_ruido_estrutural(fonte)
        for fragmento in _segmentar(limpo):
            if not _material(fragmento):
                continue
            norma = _norma_exibicao(fragmento)
            rid = _identidade(quesito_id, fragmento)
            if rid in vistos:
                continue
            vistos.add(rid)
            requisitos.append({
                "requirement_id": rid, "quesito": quesito_id, "requisito": fragmento,
                "texto_normalizado": norma, "proveniencia": proveniencia, "status": "MATERIAL",
            })
    if not requisitos:
        norma = _norma_exibicao(remover_ruido_estrutural(" ".join(fontes)))
        requisitos.append({
            "requirement_id": _identidade(quesito_id, norma or quesito_id),
            "quesito": quesito_id, "requisito": (" ".join(fontes)).strip() or quesito_id,
            "texto_normalizado": norma, "proveniencia": proveniencia,
            "status": "EXTRACAO_INDETERMINADA",
        })
    return requisitos


def termos_conteudo(texto: str) -> set[str]:
    """Termos de conteúdo (sem ruído estrutural) para avaliar se um vínculo é demonstrável."""
    return termos(remover_ruido_estrutural(texto))

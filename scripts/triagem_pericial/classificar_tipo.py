"""Classificação conservadora do tipo pericial por evidências textuais múltiplas."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


CRITERIOS = {
    "VICIOS_CONSTRUTIVOS": (
        "vicio construtivo", "defeito de construcao", "manifestacao patologica",
        "infiltracao", "fissura", "trinca", "descolamento", "imovel adquirido",
    ),
    "AVALIACAO_IMOBILIARIA": (
        "avaliacao imobiliaria", "valor de mercado", "valor do aluguel",
        "valor locativo", "metodo comparativo", "dados de mercado", "nbr 14653",
    ),
    "ENGENHARIA_RODOVIARIA": (
        "engenharia de transportes", "engenharia rodoviaria", "rodovia federal",
        "condicoes da rodovia", "seguranca viaria", "sinalizacao da rodovia",
        "acostamento", "pavimento rodoviario",
    ),
    "SINISTRO_VIARIO": (
        "acidente de transito", "acidente automobilistico", "local do acidente",
        "sinistro viario", "animal solto na pista", "fator contribuinte para o acidente",
    ),
    "ORCAMENTO_E_MEDICAO": ("medicao de servicos", "planilha orcamentaria", "memoria de calculo"),
    "ESTRUTURAS": ("pericia estrutural", "estabilidade estrutural", "risco de colapso"),
    "TOPOGRAFIA_E_DIVISAS": ("levantamento topografico", "divisa do imovel", "georreferenciamento"),
    "INSTALACOES_PREDIAIS": ("instalacao eletrica", "instalacao hidrossanitaria", "rede de esgoto"),
    "SEGURANCA_VIARIA": ("seguranca viaria", "sinalizacao de advertencia", "risco na pista"),
}

PESOS_CLASSE = {"DECISAO": 6, "DESPACHO": 5, "QUESITOS": 5, "PETICAO_INICIAL": 3,
                 "CONTESTACAO": 2, "MANIFESTACAO": 2, "PARECER_TECNICO_PARTE": 1}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", texto)


@dataclass(frozen=True)
class ResultadoTipo:
    tipo: str
    subtipos: list[str]
    nivel: str
    score: float
    evidencias: list[str]
    documentos_fonte: list[str]
    criterios: list[str]
    alternativas: list[str]


def classificar(documentos: list[dict[str, Any]]) -> ResultadoTipo:
    pontos = {tipo: 0 for tipo in CRITERIOS}
    fontes: dict[str, set[str]] = {tipo: set() for tipo in CRITERIOS}
    termos: dict[str, set[str]] = {tipo: set() for tipo in CRITERIOS}
    for documento in documentos:
        texto = normalizar("\n".join(pagina.get("texto_bruto", "") for pagina in documento["paginas"]))
        peso = PESOS_CLASSE.get(documento.get("classe_normalizada"), 1)
        for tipo, vocabulario in CRITERIOS.items():
            encontrados = {termo for termo in vocabulario if termo in texto}
            if encontrados:
                pontos[tipo] += peso * len(encontrados)
                fontes[tipo].add(documento["documento_id"])
                termos[tipo].update(encontrados)
    ranking = sorted(pontos, key=pontos.get, reverse=True)
    principal = ranking[0] if pontos[ranking[0]] else "OUTRO"
    if principal == "OUTRO":
        return ResultadoTipo("OUTRO", [], "BAIXA", 0.0, ["Nenhum critério inicial foi suficiente"],
                             [], ["Classificação conservadora"], [])
    maior, segundo = pontos[ranking[0]], pontos[ranking[1]]
    proporcao = maior / max(sum(pontos.values()), 1)
    nivel = "ALTA" if maior >= 18 and maior >= segundo * 1.5 else "MEDIA" if maior >= 6 else "BAIXA"
    subtipos = [tipo for tipo in ranking[1:] if pontos[tipo] >= max(5, maior * 0.35)]
    alternativas = [tipo for tipo in ranking[1:3] if pontos[tipo] > 0 and tipo not in subtipos]
    evidencias = [f"terminologia convergente: {termo}" for termo in sorted(termos[principal])]
    criterios = ["convergência entre múltiplas peças", "ponderação pela autoridade documental"]
    return ResultadoTipo(principal, subtipos, nivel, round(min(0.99, proporcao), 2), evidencias,
                         sorted(fontes[principal]), criterios, alternativas)

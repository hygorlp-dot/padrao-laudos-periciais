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


def classificar(documentos: list[dict[str, Any]], criterios=None) -> ResultadoTipo:
    criterios=criterios or CRITERIOS
    pontos = {tipo: 0 for tipo in criterios}
    fontes: dict[str, set[str]] = {tipo: set() for tipo in criterios}
    termos: dict[str, set[str]] = {tipo: set() for tipo in criterios}
    for documento in documentos:
        texto = normalizar("\n".join(pagina.get("texto_bruto", "") for pagina in documento["paginas"]))
        peso = PESOS_CLASSE.get(documento.get("classe_normalizada"), 1)
        for tipo, vocabulario in criterios.items():
            encontrados = {termo for termo in vocabulario if normalizar(termo) in texto}
            if encontrados:
                pontos[tipo] += peso * len(encontrados)
                fontes[tipo].add(documento["documento_id"])
                termos[tipo].update(encontrados)
    ranking = sorted(pontos,key=lambda tipo:(-pontos[tipo],tipo))
    principal = ranking[0] if pontos[ranking[0]] else "OUTRO"
    if principal == "OUTRO":
        return ResultadoTipo("OUTRO", [], "BAIXA", 0.0, ["Nenhum critério inicial foi suficiente"],
                             [], ["Classificação conservadora"], [])
    maior, segundo = pontos[ranking[0]], pontos[ranking[1]]
    proporcao = maior / max(sum(pontos.values()), 1)
    empate_relevante=segundo>0 and maior/segundo<1.25
    nivel = "ALTA" if maior >= 18 and maior >= segundo * 1.5 else "MEDIA" if maior >= 6 and not empate_relevante else "BAIXA"
    subtipos = [tipo for tipo in ranking[1:] if pontos[tipo] >= max(5, maior * 0.35)]
    alternativas = [tipo for tipo in ranking[1:] if pontos[tipo] > 0 and (empate_relevante or tipo not in subtipos)]
    evidencias = [f"terminologia convergente: {termo}" for termo in sorted(termos[principal])]
    criterios_saida=["ponderação pela autoridade documental"]
    if len(fontes[principal])>1:criterios_saida.insert(0,"convergência entre múltiplas peças independentes")
    else:criterios_saida.insert(0,"suporte localizado em uma única peça")
    return ResultadoTipo(principal, subtipos, nivel, round(min(0.99, proporcao), 2), evidencias,
                         sorted(fontes[principal]), criterios_saida, alternativas)

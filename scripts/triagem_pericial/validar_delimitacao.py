"""Valida o schema e as relações internas de uma delimitação pericial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


RAIZ = Path(__file__).resolve().parents[2]
SCHEMA = RAIZ / "schemas" / "delimitacao-pericial.schema.json"


def _duplicados(valores: list[str]) -> list[str]:
    vistos: set[str] = set()
    return sorted({valor for valor in valores if valor in vistos or vistos.add(valor)})


def validar_relacoes(delimitacao: dict[str, Any]) -> list[str]:
    """Retorna violações sem corrigir ou completar o conteúdo recebido."""
    erros: list[str] = []
    colecoes = {
        "questões técnicas": ("questoes_tecnicas", "QT"),
        "quesitos": ("quesitos", "QUE"),
        "ressalvas": ("ressalvas", "RES"),
        "conflitos": ("conflitos", "CNF"),
    }
    ids: dict[str, set[str]] = {}
    for rotulo, (chave, prefixo) in colecoes.items():
        valores = [item["id"] for item in delimitacao.get(chave, [])]
        repetidos = _duplicados(valores)
        if repetidos:
            erros.append(f"IDs duplicados em {rotulo}: {', '.join(repetidos)}")
        ids[prefixo] = set(valores)

    def conferir(referencias: list[str], prefixo: str, contexto: str) -> None:
        ausentes = sorted(set(referencias) - ids[prefixo])
        if ausentes:
            erros.append(f"{contexto} referencia IDs inexistentes: {', '.join(ausentes)}")

    for questao in delimitacao.get("questoes_tecnicas", []):
        conferir(questao["quesitos_relacionados"], "QUE", questao["id"])
        conferir(questao["ressalvas"], "RES", questao["id"])
    for quesito in delimitacao.get("quesitos", []):
        conferir(quesito["questoes_tecnicas_relacionadas"], "QT", quesito["id"])
        conferir(quesito["ressalvas_aplicaveis"], "RES", quesito["id"])
    for ressalva in delimitacao.get("ressalvas", []):
        conferir(ressalva["questoes_afetadas"], "QT", ressalva["id"])
        conferir(ressalva["quesitos_afetados"], "QUE", ressalva["id"])

    cobertura = delimitacao.get("matriz_cobertura", [])
    ids_cobertura = [item["quesito_id"] for item in cobertura]
    conferir(ids_cobertura, "QUE", "matriz de cobertura")
    repetidos = _duplicados(ids_cobertura)
    if repetidos:
        erros.append(f"Quesitos duplicados na matriz de cobertura: {', '.join(repetidos)}")
    faltantes = sorted(ids["QUE"] - set(ids_cobertura))
    if faltantes:
        erros.append(f"Quesitos ausentes da matriz de cobertura: {', '.join(faltantes)}")
    for item in cobertura:
        conferir(item["questoes_tecnicas"], "QT", f"cobertura de {item['quesito_id']}")

    if delimitacao.get("status") == "APTO_PARA_PLANEJAMENTO":
        sem_tratamento = [
            item["id"] for item in delimitacao.get("quesitos", [])
            if item["status_cobertura"] == "SEM_TRATAMENTO"
        ]
        bloqueantes = [
            item["id"] for item in delimitacao.get("conflitos", [])
            if item["classificacao"] == "BLOQUEANTE" and item["status"] != "RESOLVIDO_POR_HIERARQUIA_DE_FONTES"
        ]
        auditoria_bloqueada = [
            item["criterio"] for item in delimitacao.get("autoauditoria", [])
            if item["resultado"] == "BLOQUEADO"
        ]
        if sem_tratamento:
            erros.append("Status APTO incompatível com quesitos SEM_TRATAMENTO: " + ", ".join(sem_tratamento))
        if bloqueantes:
            erros.append("Status APTO incompatível com conflitos bloqueantes abertos: " + ", ".join(bloqueantes))
        if auditoria_bloqueada:
            erros.append("Status APTO incompatível com autoauditoria BLOQUEADA: " + "; ".join(auditoria_bloqueada))
    return erros


def validar_arquivo(caminho: Path) -> list[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    comum_path = RAIZ / "schemas" / "pje-comum.schema.json"
    comum = json.loads(comum_path.read_text(encoding="utf-8"))
    instancia = json.loads(caminho.read_text(encoding="utf-8"))
    registro = Registry().with_resource(comum["$id"], Resource.from_contents(comum))
    validador = Draft202012Validator(schema, registry=registro, format_checker=FormatChecker())
    erros = [erro.message for erro in sorted(validador.iter_errors(instancia), key=lambda e: list(e.path))]
    if not erros:
        erros.extend(validar_relacoes(instancia))
    return erros


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivos", nargs="+", type=Path)
    argumentos = parser.parse_args()
    falhas = 0
    for arquivo in argumentos.arquivos:
        erros = validar_arquivo(arquivo)
        if erros:
            falhas += 1
            print(f"FALHA: {arquivo}")
            for erro in erros:
                print(f"- {erro}")
        else:
            print(f"APROVADO: {arquivo}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())

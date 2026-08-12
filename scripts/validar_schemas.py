"""Valida os contratos JSON Schema e seus exemplos fictícios."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource


RAIZ = Path(__file__).resolve().parents[1]
PASTA_SCHEMAS = RAIZ / "schemas"
PASTAS_FIXTURES = (
    RAIZ / "tests" / "fixtures" / "auditoria",
    RAIZ / "tests" / "fixtures" / "schemas",
    RAIZ / "tests" / "fixtures" / "pje",
    RAIZ / "tests" / "fixtures" / "triagem",
    RAIZ / "tests" / "fixtures" / "planejamento",
    RAIZ / "tests" / "fixtures" / "motor-vicios",
    RAIZ / "tests" / "fixtures" / "redacao",
    RAIZ / "tests" / "fixtures" / "agentic",
)

ARQUIVOS_SCHEMA = {
    "processo": PASTA_SCHEMAS / "processo.schema.json",
    "vistoria": PASTA_SCHEMAS / "vistoria.schema.json",
    "patologia": PASTA_SCHEMAS / "patologia.schema.json",
    "laudo": PASTA_SCHEMAS / "laudo.schema.json",
    "pje-comum": PASTA_SCHEMAS / "pje-comum.schema.json",
    "manifesto-pje": PASTA_SCHEMAS / "manifesto-pje.schema.json",
    "documento-pje": PASTA_SCHEMAS / "documento-pje.schema.json",
    "delimitacao": PASTA_SCHEMAS / "delimitacao-pericial.schema.json",
    "inventario": PASTA_SCHEMAS / "inventario-referencias.schema.json",
    "conhecimento-referencial": PASTA_SCHEMAS / "conhecimento-referencial.schema.json",
    "conhecimento-normativo": PASTA_SCHEMAS / "conhecimento-normativo.schema.json",
    "plano-vistoria": PASTA_SCHEMAS / "plano-vistoria.schema.json",
    "inventario-vistoria": PASTA_SCHEMAS / "inventario-vistoria.schema.json",
    "analise-motor-vicios": PASTA_SCHEMAS / "analise-motor-vicios.schema.json",
    "fonte-online": PASTA_SCHEMAS / "fonte-online.schema.json",
    "auditoria-grounding": PASTA_SCHEMAS / "auditoria-grounding-pericial.schema.json",
    "trilha-auditoria": PASTA_SCHEMAS / "trilha-auditoria-agente.schema.json",
    "plano-redacao": PASTA_SCHEMAS / "plano-redacao.schema.json",
    "laudo-redacao": PASTA_SCHEMAS / "laudo-redacao.schema.json",
    "review-multiagente": PASTA_SCHEMAS / "review-multiagente.schema.json",
}


def carregar_json(caminho: Path) -> dict[str, Any]:
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def tipo_fixture(caminho: Path) -> str:
    if caminho.name.startswith("auditoria-grounding"):
        return "auditoria-grounding"
    if caminho.name.startswith("trilha-auditoria"):
        return "trilha-auditoria"
    prefixo = caminho.name.split("-", maxsplit=1)[0]
    if caminho.parent.name == "triagem":
        return "delimitacao"
    if caminho.parent.name == "planejamento":
        return next(nome for nome in ("conhecimento-referencial", "conhecimento-normativo", "plano-vistoria", "inventario") if caminho.name.startswith(nome))
    if caminho.parent.name == "motor-vicios":
        if caminho.name.startswith("inventario-vistoria"):
            return "inventario-vistoria"
        if caminho.name.startswith("fonte-online"):
            return "fonte-online"
        return "analise-motor-vicios"
    if caminho.parent.name == "redacao":
        return "plano-redacao" if caminho.name.startswith("plano-redacao") else "laudo-redacao"
    if caminho.parent.name == "agentic":
        return "review-multiagente"
    if caminho.parent.name == "pje":
        tipos_pje = {
            "manifesto": "manifesto-pje",
            "documento": "documento-pje",
        }
        if prefixo not in tipos_pje:
            raise ValueError(f"prefixo de fixture PJe desconhecido: {caminho.name}")
        return tipos_pje[prefixo]
    if prefixo not in ARQUIVOS_SCHEMA:
        raise ValueError(f"prefixo de fixture desconhecido: {caminho.name}")
    return prefixo


def deve_ser_valido(caminho: Path) -> bool:
    return caminho.stem.endswith(("-valido", "-valida"))


def caminho_erro(erro: ValidationError) -> str:
    if not erro.absolute_path:
        return "$"
    return "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in erro.absolute_path
    )


def principal() -> int:
    schemas = {
        nome: carregar_json(caminho) for nome, caminho in ARQUIVOS_SCHEMA.items()
    }
    registro = Registry()
    validadores: dict[str, Any] = {}

    for nome, schema in schemas.items():
        classe = validator_for(schema)
        classe.check_schema(schema)
        registro = registro.with_resource(schema["$id"], Resource.from_contents(schema))
        print(f"[OK] SCHEMA {nome}: estrutura válida")

    for nome, schema in schemas.items():
        classe = validator_for(schema)
        validadores[nome] = classe(
            schema,
            registry=registro,
            format_checker=FormatChecker(),
        )

    falhas: list[str] = []
    fixtures = sorted(
        caminho
        for pasta in PASTAS_FIXTURES
        for caminho in pasta.glob("*.json")
    )
    if not fixtures:
        falhas.append("nenhuma fixture encontrada")

    for caminho in fixtures:
        nome_schema = tipo_fixture(caminho)
        instancia = carregar_json(caminho)
        erros = sorted(
            validadores[nome_schema].iter_errors(instancia),
            key=lambda erro: list(erro.absolute_path),
        )
        esperado_valido = deve_ser_valido(caminho)

        if esperado_valido and not erros:
            print(f"[OK] ACEITO: {caminho.name}")
        elif not esperado_valido and erros:
            primeiro = erros[0]
            print(
                f"[OK] REJEITADO: {caminho.name} — "
                f"{caminho_erro(primeiro)}: {primeiro.message}"
            )
        elif esperado_valido:
            primeiro = erros[0]
            falhas.append(
                f"{caminho.name} deveria ser aceito; "
                f"{caminho_erro(primeiro)}: {primeiro.message}"
            )
        else:
            falhas.append(f"{caminho.name} deveria ser rejeitado, mas foi aceito")

    if falhas:
        print("\nVALIDAÇÃO FALHOU", file=sys.stderr)
        for falha in falhas:
            print(f"- {falha}", file=sys.stderr)
        return 1

    print(
        f"\nVALIDAÇÃO APROVADA: {len(schemas)} schemas "
        f"e {len(fixtures)} fixtures conferidos."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
